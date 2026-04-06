#!/usr/bin/env bash
set -euo pipefail

# One-command AWS provisioning + deploy for MVP usage.
# Run from repository root:
#   bash scripts/provision-and-deploy.sh

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STATE_FILE="${STATE_FILE:-${PROJECT_ROOT}/.aws-provision-state.json}"
ENV_FILE="${ENV_FILE:-${PROJECT_ROOT}/.env}"
DRY_RUN=false
AUTO_YES=false
REUSE_EXISTING=true

usage() {
  cat <<'EOF'
Usage: bash scripts/provision-and-deploy.sh [options]

Options:
  --dry-run       Print actions without executing AWS/SSH mutating steps.
  --yes           Skip confirmation prompts.
  --no-reuse      Force creating a new stack (ignore existing state).
  --help          Show this help.
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY_RUN=true ;;
    --yes) AUTO_YES=true ;;
    --no-reuse) REUSE_EXISTING=false ;;
    --help|-h) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage; exit 1 ;;
  esac
  shift
done

if ! command -v aws >/dev/null 2>&1; then
  echo "aws CLI is required." >&2
  exit 1
fi

run_cmd() {
  if [ "${DRY_RUN}" = "true" ]; then
    echo "[dry-run] $*"
  else
    eval "$@"
  fi
}

confirm_or_exit() {
  local prompt="$1"
  if [ "${AUTO_YES}" = "true" ]; then
    return 0
  fi
  printf "%s [y/N]: " "${prompt}" >&2
  read -r ans
  case "${ans}" in
    y|Y|yes|YES) ;;
    *) echo "Aborted."; exit 1 ;;
  esac
}

if [ ! -f "${ENV_FILE}" ]; then
  if [ -f "${PROJECT_ROOT}/.env.example" ]; then
    cp "${PROJECT_ROOT}/.env.example" "${ENV_FILE}"
    echo "Created ${ENV_FILE}. Update values and re-run."
  else
    echo "Missing ${ENV_FILE} and .env.example" >&2
  fi
  exit 1
fi

# shellcheck disable=SC1090
set -a && source "${ENV_FILE}" && set +a

require_var() {
  local n="$1"
  if [ -z "${!n:-}" ]; then
    echo "Missing required variable: ${n}" >&2
    exit 1
  fi
}

require_var AWS_REGION
require_var DEPLOY_PATH
require_var PRIMARY_DOMAIN
require_var CERTBOT_EMAIL
require_var MYSQL_ROOT_PASSWORD
require_var MYSQL_PASSWORD
require_var ADMIN_PASSWORD

STACK_PREFIX="${STACK_PREFIX:-${COMPOSE_PROJECT_NAME:-theiux}}"
STACK_ID="${STACK_ID:-$(date +%s)}"
STACK_NAME="${STACK_NAME:-${STACK_PREFIX}-${STACK_ID}}"
INSTANCE_TYPE="${INSTANCE_TYPE:-t3.small}"
ROOT_VOLUME_SIZE_GB="${ROOT_VOLUME_SIZE_GB:-40}"
SSH_CIDR="${SSH_CIDR:-0.0.0.0/0}"
APP_USER="${APP_USER:-ubuntu}"
LOCAL_IMAGE_REPO="${LOCAL_IMAGE_REPO:-${STACK_PREFIX}-frappe}"
USE_INTERNAL_DB="${USE_INTERNAL_DB:-true}"
USE_INTERNAL_REDIS="${USE_INTERNAL_REDIS:-true}"
APPS_JSON_FILE="${APPS_JSON_FILE:-}"
AUTO_TERMINATION_PROTECTION="${AUTO_TERMINATION_PROTECTION:-false}"

state_val() {
  local key="$1"
  python3 - "${STATE_FILE}" "${key}" <<'PY'
import json,sys
state_path,key=sys.argv[1],sys.argv[2]
try:
    d=json.load(open(state_path))
except Exception:
    print("")
    raise SystemExit(0)
v=d.get(key,"")
print(v if v is not None else "")
PY
}

if [ -f "${STATE_FILE}" ] && [ "${REUSE_EXISTING}" = "true" ]; then
  EXISTING_INSTANCE_ID="$(state_val instance_id)"
  EXISTING_REGION="$(state_val aws_region)"
  if [ -n "${EXISTING_INSTANCE_ID}" ] && [ -n "${EXISTING_REGION}" ]; then
    INSTANCE_STATE="$(aws ec2 describe-instances --region "${EXISTING_REGION}" --instance-ids "${EXISTING_INSTANCE_ID}" --query 'Reservations[0].Instances[0].State.Name' --output text 2>/dev/null || true)"
    if [ "${INSTANCE_STATE}" = "running" ] || [ "${INSTANCE_STATE}" = "pending" ] || [ "${INSTANCE_STATE}" = "stopped" ]; then
      EXISTING_IP="$(state_val public_ip)"
      echo "Reusing existing stack from ${STATE_FILE}"
      echo "Instance: ${EXISTING_INSTANCE_ID} (${INSTANCE_STATE})"
      echo "Public IP: ${EXISTING_IP}"
      echo "No new AWS resources created."
      exit 0
    fi
  fi
fi

ACCOUNT_ID="$(aws sts get-caller-identity --query 'Account' --output text)"
VPC_ID="$(aws ec2 describe-vpcs --filters Name=isDefault,Values=true --region "${AWS_REGION}" --query 'Vpcs[0].VpcId' --output text)"
SUBNET_ID="$(aws ec2 describe-subnets --filters Name=default-for-az,Values=true --region "${AWS_REGION}" --query 'Subnets[0].SubnetId' --output text)"
AMI_ID="$(aws ssm get-parameter --name "/aws/service/canonical/ubuntu/server/22.04/stable/current/amd64/hvm/ebs-gp2/ami-id" --region "${AWS_REGION}" --query 'Parameter.Value' --output text)"

KEY_NAME="${KEY_NAME:-${STACK_NAME}-key}"
SG_NAME="${SG_NAME:-${STACK_NAME}-sg}"
ROLE_NAME="${ROLE_NAME:-${STACK_NAME}-role}"
INSTANCE_PROFILE_NAME="${INSTANCE_PROFILE_NAME:-${STACK_NAME}-profile}"
S3_ARTIFACT_BUCKET="${S3_ARTIFACT_BUCKET:-${STACK_PREFIX}-${ACCOUNT_ID}-${STACK_ID}-artifacts}"
S3_ARTIFACT_KEY="${S3_ARTIFACT_KEY:-${STACK_NAME}/source.tar.gz}"
KEY_PATH="${KEY_PATH:-${PROJECT_ROOT}/${KEY_NAME}.pem}"

if [ -n "${APPS_JSON_FILE}" ]; then
  if [ ! -f "${APPS_JSON_FILE}" ]; then
    echo "APPS_JSON_FILE not found: ${APPS_JSON_FILE}" >&2
    exit 1
  fi
  APPS_JSON_BASE64_VALUE="$(base64 -w0 "${APPS_JSON_FILE}")"
else
  APPS_JSON_BASE64_VALUE="${APPS_JSON_BASE64:-}"
fi

confirm_or_exit "Provision stack ${STACK_NAME} in ${AWS_REGION}?"
echo "Creating IAM role/profile..."
TRUST_DOC="$(mktemp)"
cat > "${TRUST_DOC}" <<'JSON'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": { "Service": "ec2.amazonaws.com" },
      "Action": "sts:AssumeRole"
    }
  ]
}
JSON

if ! aws iam get-role --role-name "${ROLE_NAME}" >/dev/null 2>&1; then
  run_cmd "aws iam create-role --role-name \"${ROLE_NAME}\" --assume-role-policy-document \"file://${TRUST_DOC}\" >/dev/null"
  run_cmd "aws iam attach-role-policy --role-name \"${ROLE_NAME}\" --policy-arn arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore >/dev/null"
  run_cmd "aws iam attach-role-policy --role-name \"${ROLE_NAME}\" --policy-arn arn:aws:iam::aws:policy/AmazonS3FullAccess >/dev/null"
  run_cmd "aws iam attach-role-policy --role-name \"${ROLE_NAME}\" --policy-arn arn:aws:iam::aws:policy/AmazonEC2FullAccess >/dev/null"
  run_cmd "aws iam attach-role-policy --role-name \"${ROLE_NAME}\" --policy-arn arn:aws:iam::aws:policy/AmazonRoute53FullAccess >/dev/null"
fi

if ! aws iam get-instance-profile --instance-profile-name "${INSTANCE_PROFILE_NAME}" >/dev/null 2>&1; then
  run_cmd "aws iam create-instance-profile --instance-profile-name \"${INSTANCE_PROFILE_NAME}\" >/dev/null"
  sleep 3
fi
if ! aws iam get-instance-profile --instance-profile-name "${INSTANCE_PROFILE_NAME}" --query "InstanceProfile.Roles[?RoleName=='${ROLE_NAME}'] | length(@)" --output text | grep -q '^1$'; then
  run_cmd "aws iam add-role-to-instance-profile --instance-profile-name \"${INSTANCE_PROFILE_NAME}\" --role-name \"${ROLE_NAME}\" >/dev/null || true"
fi

echo "Creating security group..."
SG_ID="$(aws ec2 describe-security-groups --region "${AWS_REGION}" --filters Name=group-name,Values="${SG_NAME}" Name=vpc-id,Values="${VPC_ID}" --query 'SecurityGroups[0].GroupId' --output text)"
if [ "${SG_ID}" = "None" ] || [ -z "${SG_ID}" ]; then
  if [ "${DRY_RUN}" = "true" ]; then
    echo "[dry-run] aws ec2 create-security-group ... -> SG_ID"
    SG_ID="dry-run-sg"
  else
    SG_ID="$(aws ec2 create-security-group --region "${AWS_REGION}" --group-name "${SG_NAME}" --description "theiux access" --vpc-id "${VPC_ID}" --query 'GroupId' --output text)"
  fi
  run_cmd "aws ec2 authorize-security-group-ingress --region \"${AWS_REGION}\" --group-id \"${SG_ID}\" --ip-permissions '[
    {\"IpProtocol\":\"tcp\",\"FromPort\":22,\"ToPort\":22,\"IpRanges\":[{\"CidrIp\":\"${SSH_CIDR}\"}]},
    {\"IpProtocol\":\"tcp\",\"FromPort\":80,\"ToPort\":80,\"IpRanges\":[{\"CidrIp\":\"0.0.0.0/0\"}]},
    {\"IpProtocol\":\"tcp\",\"FromPort\":443,\"ToPort\":443,\"IpRanges\":[{\"CidrIp\":\"0.0.0.0/0\"}]}
  ]' >/dev/null"
fi

echo "Creating key pair..."
if ! aws ec2 describe-key-pairs --region "${AWS_REGION}" --key-names "${KEY_NAME}" >/dev/null 2>&1; then
  if [ "${DRY_RUN}" = "true" ]; then
    echo "[dry-run] aws ec2 create-key-pair --key-name ${KEY_NAME} > ${KEY_PATH}"
  else
    aws ec2 create-key-pair --region "${AWS_REGION}" --key-name "${KEY_NAME}" --query 'KeyMaterial' --output text > "${KEY_PATH}"
    chmod 600 "${KEY_PATH}"
  fi
fi

echo "Creating/uploading deploy artifact..."
if ! aws s3api head-bucket --bucket "${S3_ARTIFACT_BUCKET}" --region "${AWS_REGION}" >/dev/null 2>&1; then
  if [ "${AWS_REGION}" = "us-east-1" ]; then
    run_cmd "aws s3api create-bucket --bucket \"${S3_ARTIFACT_BUCKET}\" >/dev/null"
  else
    run_cmd "aws s3api create-bucket --bucket \"${S3_ARTIFACT_BUCKET}\" --create-bucket-configuration \"LocationConstraint=${AWS_REGION}\" >/dev/null"
  fi
fi

ARTIFACT_PATH="$(mktemp --suffix=.tar.gz)"
tar \
  --exclude=.git \
  --exclude=.aws-provision-state.json \
  --exclude=.env \
  --exclude='*.pem' \
  --exclude='*.tar.gz' \
  -czf "${ARTIFACT_PATH}" -C "${PROJECT_ROOT}" .
run_cmd "aws s3 cp \"${ARTIFACT_PATH}\" \"s3://${S3_ARTIFACT_BUCKET}/${S3_ARTIFACT_KEY}\" --region \"${AWS_REGION}\" >/dev/null"

USER_DATA_FILE="$(mktemp)"
cat > "${USER_DATA_FILE}" <<EOF
#!/bin/bash
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y ca-certificates curl gnupg lsb-release unzip jq awscli
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=\$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu \$(. /etc/os-release && echo \$VERSION_CODENAME) stable" > /etc/apt/sources.list.d/docker.list
apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
systemctl enable docker
systemctl start docker
usermod -aG docker "${APP_USER}" || true

mkdir -p "${DEPLOY_PATH}"
aws s3 cp "s3://${S3_ARTIFACT_BUCKET}/${S3_ARTIFACT_KEY}" /tmp/theiux-source.tar.gz --region "${AWS_REGION}"
tar -xzf /tmp/theiux-source.tar.gz -C "${DEPLOY_PATH}"

if [ ! -f "${DEPLOY_PATH}/.env" ]; then
  cp "${DEPLOY_PATH}/.env.example" "${DEPLOY_PATH}/.env"
fi

upsert_env() {
  local key="\$1"
  local val="\$2"
  if grep -q "^\${key}=" "${DEPLOY_PATH}/.env"; then
    sed -i "s|^\${key}=.*|\${key}=\${val}|" "${DEPLOY_PATH}/.env"
  else
    echo "\${key}=\${val}" >> "${DEPLOY_PATH}/.env"
  fi
}

upsert_env AWS_REGION "${AWS_REGION}"
upsert_env DEPLOY_PATH "${DEPLOY_PATH}"
upsert_env FRAPPE_IMAGE_REPO "${LOCAL_IMAGE_REPO}"
upsert_env IMAGE_TAG "latest"
upsert_env PRIMARY_DOMAIN "${PRIMARY_DOMAIN}"
upsert_env CERTBOT_EMAIL "${CERTBOT_EMAIL}"
upsert_env MYSQL_ROOT_PASSWORD "${MYSQL_ROOT_PASSWORD}"
upsert_env MYSQL_PASSWORD "${MYSQL_PASSWORD}"
upsert_env ADMIN_PASSWORD "${ADMIN_PASSWORD}"
upsert_env APPS_JSON_BASE64 "${APPS_JSON_BASE64_VALUE}"

cd "${DEPLOY_PATH}"
docker build \
  --build-arg PYTHON_VERSION="${PYTHON_VERSION}" \
  --build-arg NODE_VERSION="${NODE_VERSION}" \
  --build-arg WKHTMLTOPDF_VERSION="${WKHTMLTOPDF_VERSION}" \
  --build-arg FRAPPE_BASE_VERSION="${FRAPPE_VERSION}" \
  --build-arg APPS_JSON_BASE64="${APPS_JSON_BASE64_VALUE}" \
  -f docker/frappe/Dockerfile \
  -t "${LOCAL_IMAGE_REPO}:latest" .

PROFILE_ARGS=""
[ "${USE_INTERNAL_DB}" = "true" ] && PROFILE_ARGS="\${PROFILE_ARGS} --profile internal-db"
[ "${USE_INTERNAL_REDIS}" = "true" ] && PROFILE_ARGS="\${PROFILE_ARGS} --profile internal-redis"
docker compose \${PROFILE_ARGS} up -d --remove-orphans
EOF

echo "Launching EC2 instance..."
if [ "${DRY_RUN}" = "true" ]; then
  INSTANCE_ID="i-dryrun"
else
INSTANCE_ID="$(aws ec2 run-instances \
  --region "${AWS_REGION}" \
  --image-id "${AMI_ID}" \
  --instance-type "${INSTANCE_TYPE}" \
  --iam-instance-profile Name="${INSTANCE_PROFILE_NAME}" \
  --key-name "${KEY_NAME}" \
  --security-group-ids "${SG_ID}" \
  --subnet-id "${SUBNET_ID}" \
  --associate-public-ip-address \
  --block-device-mappings "[{\"DeviceName\":\"/dev/sda1\",\"Ebs\":{\"VolumeSize\":${ROOT_VOLUME_SIZE_GB},\"VolumeType\":\"gp3\",\"DeleteOnTermination\":true}}]" \
  --user-data "file://${USER_DATA_FILE}" \
  --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=${STACK_NAME}}]" \
  --query 'Instances[0].InstanceId' --output text)"
fi

if [ "${AUTO_TERMINATION_PROTECTION}" = "true" ]; then
  run_cmd "aws ec2 modify-instance-attribute --region \"${AWS_REGION}\" --instance-id \"${INSTANCE_ID}\" --disable-api-termination"
fi

run_cmd "aws ec2 wait instance-running --region \"${AWS_REGION}\" --instance-ids \"${INSTANCE_ID}\""
run_cmd "aws ec2 wait instance-status-ok --region \"${AWS_REGION}\" --instance-ids \"${INSTANCE_ID}\""

if [ "${DRY_RUN}" = "true" ]; then
  PUBLIC_IP="0.0.0.0"
else
  PUBLIC_IP="$(aws ec2 describe-instances --region "${AWS_REGION}" --instance-ids "${INSTANCE_ID}" --query 'Reservations[0].Instances[0].PublicIpAddress' --output text)"
fi
EIP_ALLOCATION_ID=""
MANAGED_EIP="false"

if [ "${RUN_EIP_SETUP:-false}" = "true" ]; then
  if [ -n "${EIP_ALLOCATION_ID:-}" ]; then
    aws ec2 associate-address --region "${AWS_REGION}" --instance-id "${INSTANCE_ID}" --allocation-id "${EIP_ALLOCATION_ID}" --allow-reassociation >/dev/null
  else
    if [ "${DRY_RUN}" = "true" ]; then
      EIP_ALLOCATION_ID="eipalloc-dryrun"
    else
      EIP_ALLOCATION_ID="$(aws ec2 allocate-address --region "${AWS_REGION}" --domain vpc --query 'AllocationId' --output text)"
    fi
    run_cmd "aws ec2 associate-address --region \"${AWS_REGION}\" --instance-id \"${INSTANCE_ID}\" --allocation-id \"${EIP_ALLOCATION_ID}\" --allow-reassociation >/dev/null"
    MANAGED_EIP="true"
  fi
  if [ "${DRY_RUN}" != "true" ]; then
    PUBLIC_IP="$(aws ec2 describe-addresses --region "${AWS_REGION}" --allocation-ids "${EIP_ALLOCATION_ID}" --query 'Addresses[0].PublicIp' --output text)"
  fi
fi

if [ "${DRY_RUN}" != "true" ]; then
cat > "${STATE_FILE}" <<JSON
{
  "stack_name": "${STACK_NAME}",
  "aws_region": "${AWS_REGION}",
  "instance_id": "${INSTANCE_ID}",
  "public_ip": "${PUBLIC_IP}",
  "security_group_id": "${SG_ID}",
  "security_group_name": "${SG_NAME}",
  "key_name": "${KEY_NAME}",
  "key_path": "${KEY_PATH}",
  "iam_role_name": "${ROLE_NAME}",
  "instance_profile_name": "${INSTANCE_PROFILE_NAME}",
  "s3_bucket": "${S3_ARTIFACT_BUCKET}",
  "s3_key": "${S3_ARTIFACT_KEY}",
  "eip_allocation_id": "${EIP_ALLOCATION_ID}",
  "managed_eip": "${MANAGED_EIP}",
  "deploy_path": "${DEPLOY_PATH}"
}
JSON
fi

if [ "${AUTO_ROUTE53_DNS:-true}" = "true" ] && [ -n "${DOMAIN_NAME:-}" ] && [ "${DRY_RUN}" != "true" ]; then
  echo "Updating Route53 A records for ${DOMAIN_NAME} -> ${PUBLIC_IP}..."
  DOMAIN_NAME="${DOMAIN_NAME}" CREATE_WWW_RECORD="${CREATE_WWW_RECORD:-true}" AUTO_ROUTE53_DNS="${AUTO_ROUTE53_DNS:-true}" \
    HOSTED_ZONE_ID="${HOSTED_ZONE_ID:-}" \
    bash "${PROJECT_ROOT}/scripts/route53-sync-dns.sh" --ip "${PUBLIC_IP}" || echo "WARN: Route53 sync failed (non-fatal)." >&2
fi

echo "Waiting for cloud-init and service health..."
run_cmd "ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -i \"${KEY_PATH}\" \"${APP_USER}@${PUBLIC_IP}\" \"cloud-init status --wait >/dev/null && cd '${DEPLOY_PATH}' && sudo docker compose ps\""

echo
echo "Provision + deploy completed."
echo "Instance: ${INSTANCE_ID}"
echo "Public IP: ${PUBLIC_IP}"
echo "State file: ${STATE_FILE}"
echo "Ping check:"
echo "curl -H 'Host: ${PRIMARY_DOMAIN}' http://${PUBLIC_IP}/api/method/ping"
