#!/usr/bin/env bash
# Upsert apex (+ optional www) A records to the stack public IP in Route53.
# Fully automatable: resolves zone by DOMAIN_NAME if HOSTED_ZONE_ID is unset.
# Set AUTO_ROUTE53_DNS=false to skip.
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STATE_FILE="${PROJECT_ROOT}/.aws-provision-state.json"
ENV_FILE="${PROJECT_ROOT}/.env"

ZONE_ID=""
DOMAIN_NAME=""
CREATE_WWW_RECORD="true"
PUBLIC_IP=""
AUTO_ROUTE53_DNS="true"

while [ $# -gt 0 ]; do
  case "$1" in
    --zone-id) ZONE_ID="${2:-}"; shift 2 ;;
    --ip) PUBLIC_IP="${2:-}"; shift 2 ;;
    *) echo "Usage: $0 [--zone-id Z...] [--ip x.x.x.x]" >&2; exit 1 ;;
  esac
done

if [ -f "${ENV_FILE}" ]; then
  # shellcheck disable=SC1090
  set -a && source "${ENV_FILE}" && set +a
fi

ZONE_ID="${ZONE_ID:-${HOSTED_ZONE_ID:-}}"
DOMAIN_NAME="${DOMAIN_NAME:-roguesingh.cloud}"
CREATE_WWW_RECORD="${CREATE_WWW_RECORD:-true}"
AUTO_ROUTE53_DNS="${AUTO_ROUTE53_DNS:-true}"

if [ "${AUTO_ROUTE53_DNS}" != "true" ]; then
  echo "route53-sync-dns: skipped (AUTO_ROUTE53_DNS=${AUTO_ROUTE53_DNS})"
  exit 0
fi

if [ -z "${ZONE_ID}" ] && [ -n "${DOMAIN_NAME}" ]; then
  raw="$(aws route53 list-hosted-zones-by-name --dns-name "${DOMAIN_NAME}." --query 'HostedZones[0].Id' --output text 2>/dev/null || true)"
  ZONE_ID="${raw#/hostedzone/}"
  if [ "${ZONE_ID}" = "None" ] || [ -z "${ZONE_ID}" ]; then
    ZONE_ID=""
  fi
fi

if [ -z "${ZONE_ID}" ]; then
  echo "route53-sync-dns: skipped (no hosted zone for ${DOMAIN_NAME}; set HOSTED_ZONE_ID or create a public zone)" >&2
  exit 0
fi

if [ -z "${PUBLIC_IP}" ] && [ -f "${STATE_FILE}" ]; then
  PUBLIC_IP="$(python3 -c "import json; print(json.load(open('${STATE_FILE}')).get('public_ip',''))" 2>/dev/null || true)"
fi

if [ -z "${PUBLIC_IP}" ] && [ -f "${STATE_FILE}" ]; then
  IID="$(python3 -c "import json; print(json.load(open('${STATE_FILE}')).get('instance_id',''))" 2>/dev/null || true)"
  RGN="$(python3 -c "import json; print(json.load(open('${STATE_FILE}')).get('aws_region',''))" 2>/dev/null || true)"
  RGN="${RGN:-${AWS_REGION:-}}"
  if [ -n "${IID}" ] && [ -n "${RGN}" ]; then
    PUBLIC_IP="$(aws ec2 describe-instances --region "${RGN}" --instance-ids "${IID}" --query 'Reservations[0].Instances[0].PublicIpAddress' --output text 2>/dev/null || true)"
    if [ "${PUBLIC_IP}" = "None" ]; then
      PUBLIC_IP=""
    fi
  fi
fi

if [ -z "${PUBLIC_IP}" ]; then
  echo "route53-sync-dns: skipped (no public IP; pass --ip or populate .aws-provision-state.json)" >&2
  exit 0
fi

BATCH="$(mktemp)"
trap 'rm -f "${BATCH}"' EXIT

if [ "${CREATE_WWW_RECORD}" = "true" ]; then
  python3 - <<PY
import json
ip = "${PUBLIC_IP}"
d = "${DOMAIN_NAME}"
out = {
  "Comment": "theiux: sync apex and www to EC2",
  "Changes": [
    {
      "Action": "UPSERT",
      "ResourceRecordSet": {
        "Name": d + ".",
        "Type": "A",
        "TTL": 60,
        "ResourceRecords": [{"Value": ip}],
      }
    },
    {
      "Action": "UPSERT",
      "ResourceRecordSet": {
        "Name": "www." + d + ".",
        "Type": "A",
        "TTL": 60,
        "ResourceRecords": [{"Value": ip}],
      }
    },
  ],
}
open("${BATCH}", "w").write(json.dumps(out))
PY
else
  python3 - <<PY
import json
ip = "${PUBLIC_IP}"
d = "${DOMAIN_NAME}"
out = {
  "Comment": "theiux: sync apex to EC2",
  "Changes": [
    {
      "Action": "UPSERT",
      "ResourceRecordSet": {
        "Name": d + ".",
        "Type": "A",
        "TTL": 60,
        "ResourceRecords": [{"Value": ip}],
      }
    },
  ],
}
open("${BATCH}", "w").write(json.dumps(out))
PY
fi

aws route53 change-resource-record-sets \
  --hosted-zone-id "${ZONE_ID}" \
  --change-batch "file://${BATCH}" \
  --output json

if [ "${CREATE_WWW_RECORD}" = "true" ]; then
  echo "route53-sync-dns: UPSERT ${DOMAIN_NAME} + www.${DOMAIN_NAME} -> ${PUBLIC_IP}"
else
  echo "route53-sync-dns: UPSERT ${DOMAIN_NAME} -> ${PUBLIC_IP}"
fi
