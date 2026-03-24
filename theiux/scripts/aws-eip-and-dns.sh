#!/usr/bin/env bash
set -euo pipefail

AWS_REGION="${AWS_REGION:-us-east-1}"
EIP_ALLOCATION_ID="${EIP_ALLOCATION_ID:-}"
AUTO_ALLOCATE_EIP="${AUTO_ALLOCATE_EIP:-true}"
HOSTED_ZONE_ID="${HOSTED_ZONE_ID:-}"
DOMAIN_NAME="${DOMAIN_NAME:-}"
CREATE_WWW_RECORD="${CREATE_WWW_RECORD:-true}"

TOKEN="$(curl -sS -X PUT "http://169.254.169.254/latest/api/token" -H "X-aws-ec2-metadata-token-ttl-seconds: 300")"
INSTANCE_ID="$(curl -sS -H "X-aws-ec2-metadata-token: ${TOKEN}" "http://169.254.169.254/latest/meta-data/instance-id")"

if [ -z "${EIP_ALLOCATION_ID}" ]; then
  if [ "${AUTO_ALLOCATE_EIP}" != "true" ]; then
    echo "EIP_ALLOCATION_ID is not set and AUTO_ALLOCATE_EIP is false." >&2
    exit 1
  fi
  EIP_ALLOCATION_ID="$(aws ec2 allocate-address --domain vpc --region "${AWS_REGION}" --query 'AllocationId' --output text)"
fi

aws ec2 associate-address \
  --instance-id "${INSTANCE_ID}" \
  --allocation-id "${EIP_ALLOCATION_ID}" \
  --allow-reassociation \
  --region "${AWS_REGION}" >/dev/null

PUBLIC_IP="$(aws ec2 describe-addresses --allocation-ids "${EIP_ALLOCATION_ID}" --region "${AWS_REGION}" --query 'Addresses[0].PublicIp' --output text)"
echo "Elastic IP associated: ${PUBLIC_IP}"

if [ -n "${HOSTED_ZONE_ID}" ] && [ -n "${DOMAIN_NAME}" ]; then
  cat > /tmp/theiux-route53.json <<EOF
{
  "Comment": "Automatic DNS update for theiux",
  "Changes": [
    {
      "Action": "UPSERT",
      "ResourceRecordSet": {
        "Name": "${DOMAIN_NAME}",
        "Type": "A",
        "TTL": 60,
        "ResourceRecords": [{ "Value": "${PUBLIC_IP}" }]
      }
    }
  ]
}
EOF

  if [ "${CREATE_WWW_RECORD}" = "true" ]; then
    cat > /tmp/theiux-route53.json <<EOF
{
  "Comment": "Automatic DNS update for theiux",
  "Changes": [
    {
      "Action": "UPSERT",
      "ResourceRecordSet": {
        "Name": "${DOMAIN_NAME}",
        "Type": "A",
        "TTL": 60,
        "ResourceRecords": [{ "Value": "${PUBLIC_IP}" }]
      }
    },
    {
      "Action": "UPSERT",
      "ResourceRecordSet": {
        "Name": "www.${DOMAIN_NAME}",
        "Type": "A",
        "TTL": 60,
        "ResourceRecords": [{ "Value": "${PUBLIC_IP}" }]
      }
    }
  ]
}
EOF
  fi

  aws route53 change-resource-record-sets \
    --hosted-zone-id "${HOSTED_ZONE_ID}" \
    --change-batch file:///tmp/theiux-route53.json >/dev/null

  echo "Route53 records updated for ${DOMAIN_NAME}"
fi
