#!/usr/bin/env bash
set -euo pipefail

# Destroys resources created by provision-and-deploy.sh.
# Usage:
#   bash scripts/destroy.sh
#   STATE_FILE=/path/to/state.json bash scripts/destroy.sh

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STATE_FILE="${STATE_FILE:-${PROJECT_ROOT}/.aws-provision-state.json}"
DELETE_BUCKET="${DELETE_BUCKET:-true}"
DELETE_KEY_FILE="${DELETE_KEY_FILE:-false}"
DRY_RUN=false
AUTO_YES=false

usage() {
  cat <<'EOF'
Usage: bash scripts/destroy.sh [options]

Options:
  --dry-run   Print actions only.
  --yes       Skip confirmation prompt.
  --help      Show this help.
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY_RUN=true ;;
    --yes) AUTO_YES=true ;;
    --help|-h) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage; exit 1 ;;
  esac
  shift
done

if [ ! -f "${STATE_FILE}" ]; then
  echo "State file not found: ${STATE_FILE}" >&2
  exit 1
fi

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

if [ "${AUTO_YES}" != "true" ]; then
  printf "Destroy resources from %s ? [y/N]: " "${STATE_FILE}" >&2
  read -r ans
  case "${ans}" in
    y|Y|yes|YES) ;;
    *) echo "Aborted."; exit 1 ;;
  esac
fi

val() {
  local k="$1"
  python3 - "${STATE_FILE}" "${k}" <<'PY'
import json,sys
p,k=sys.argv[1],sys.argv[2]
d=json.load(open(p))
print(d.get(k,""))
PY
}

AWS_REGION="$(val aws_region)"
INSTANCE_ID="$(val instance_id)"
EIP_ALLOCATION_ID="$(val eip_allocation_id)"
MANAGED_EIP="$(val managed_eip)"
SG_ID="$(val security_group_id)"
KEY_NAME="$(val key_name)"
KEY_PATH="$(val key_path)"
ROLE_NAME="$(val iam_role_name)"
INSTANCE_PROFILE_NAME="$(val instance_profile_name)"
S3_BUCKET="$(val s3_bucket)"
S3_KEY="$(val s3_key)"

echo "Terminating EC2 instance..."
if [ -n "${INSTANCE_ID}" ] && aws ec2 describe-instances --region "${AWS_REGION}" --instance-ids "${INSTANCE_ID}" >/dev/null 2>&1; then
  run_cmd "aws ec2 terminate-instances --region \"${AWS_REGION}\" --instance-ids \"${INSTANCE_ID}\" >/dev/null || true"
  run_cmd "aws ec2 wait instance-terminated --region \"${AWS_REGION}\" --instance-ids \"${INSTANCE_ID}\" || true"
fi

if [ -n "${EIP_ALLOCATION_ID}" ] && [ "${MANAGED_EIP}" = "true" ]; then
  echo "Releasing managed EIP..."
  ASSOC_ID="$(aws ec2 describe-addresses --region "${AWS_REGION}" --allocation-ids "${EIP_ALLOCATION_ID}" --query 'Addresses[0].AssociationId' --output text 2>/dev/null || true)"
  if [ -n "${ASSOC_ID}" ] && [ "${ASSOC_ID}" != "None" ]; then
    run_cmd "aws ec2 disassociate-address --region \"${AWS_REGION}\" --association-id \"${ASSOC_ID}\" >/dev/null || true"
  fi
  run_cmd "aws ec2 release-address --region \"${AWS_REGION}\" --allocation-id \"${EIP_ALLOCATION_ID}\" >/dev/null || true"
fi

echo "Deleting key pair..."
if [ -n "${KEY_NAME}" ]; then
  run_cmd "aws ec2 delete-key-pair --region \"${AWS_REGION}\" --key-name \"${KEY_NAME}\" >/dev/null || true"
fi
if [ "${DELETE_KEY_FILE}" = "true" ] && [ -n "${KEY_PATH}" ] && [ -f "${KEY_PATH}" ]; then
  run_cmd "rm -f \"${KEY_PATH}\""
fi

echo "Deleting security group..."
if [ -n "${SG_ID}" ]; then
  run_cmd "aws ec2 delete-security-group --region \"${AWS_REGION}\" --group-id \"${SG_ID}\" >/dev/null || true"
fi

echo "Deleting IAM profile/role..."
if [ -n "${INSTANCE_PROFILE_NAME}" ]; then
  run_cmd "aws iam remove-role-from-instance-profile --instance-profile-name \"${INSTANCE_PROFILE_NAME}\" --role-name \"${ROLE_NAME}\" >/dev/null 2>&1 || true"
  run_cmd "aws iam delete-instance-profile --instance-profile-name \"${INSTANCE_PROFILE_NAME}\" >/dev/null 2>&1 || true"
fi
if [ -n "${ROLE_NAME}" ]; then
  run_cmd "aws iam detach-role-policy --role-name \"${ROLE_NAME}\" --policy-arn arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore >/dev/null 2>&1 || true"
  run_cmd "aws iam detach-role-policy --role-name \"${ROLE_NAME}\" --policy-arn arn:aws:iam::aws:policy/AmazonS3FullAccess >/dev/null 2>&1 || true"
  run_cmd "aws iam detach-role-policy --role-name \"${ROLE_NAME}\" --policy-arn arn:aws:iam::aws:policy/AmazonEC2FullAccess >/dev/null 2>&1 || true"
  run_cmd "aws iam delete-role --role-name \"${ROLE_NAME}\" >/dev/null 2>&1 || true"
fi

if [ "${DELETE_BUCKET}" = "true" ] && [ -n "${S3_BUCKET}" ]; then
  echo "Deleting S3 artifact objects..."
  run_cmd "aws s3 rm \"s3://${S3_BUCKET}/${S3_KEY}\" --region \"${AWS_REGION}\" >/dev/null 2>&1 || true"
  run_cmd "aws s3 rb \"s3://${S3_BUCKET}\" --force --region \"${AWS_REGION}\" >/dev/null 2>&1 || true"
fi

if [ "${DRY_RUN}" = "true" ]; then
  echo "[dry-run] rm -f \"${STATE_FILE}\""
  echo "Destroy dry-run completed."
else
  rm -f "${STATE_FILE}"
  echo "Destroy completed. State file removed."
fi
