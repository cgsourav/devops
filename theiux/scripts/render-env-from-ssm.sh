#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="${PROJECT_ROOT:-/opt/theiux}"
PARAMETER_PATH="${PARAMETER_PATH:-/theiux/prod}"
AWS_REGION="${AWS_REGION:-us-east-1}"
ENV_FILE="${PROJECT_ROOT}/.env"

mkdir -p "${PROJECT_ROOT}"

if [ -f "${PROJECT_ROOT}/.env.example" ]; then
  cp "${PROJECT_ROOT}/.env.example" "${ENV_FILE}"
else
  : > "${ENV_FILE}"
fi

fetch_param() {
  local key="$1"
  aws ssm get-parameter \
    --region "${AWS_REGION}" \
    --with-decryption \
    --name "${PARAMETER_PATH}/${key}" \
    --query 'Parameter.Value' \
    --output text
}

upsert_env() {
  local key="$1"
  local value="$2"
  if grep -q "^${key}=" "${ENV_FILE}"; then
    sed -i "s|^${key}=.*|${key}=${value}|" "${ENV_FILE}"
  else
    echo "${key}=${value}" >> "${ENV_FILE}"
  fi
}

# Optional non-secret controls.
upsert_env AWS_REGION "${AWS_REGION}"
upsert_env ACTIVE_COLOR "${ACTIVE_COLOR:-blue}"

# Secret and runtime values are read from Parameter Store.
for key in SITE_HOSTS PRIMARY_DOMAIN CERTBOT_EMAIL MYSQL_ROOT_PASSWORD MYSQL_PASSWORD ADMIN_PASSWORD HEALTHCHECK_HOST HEALTHCHECK_URL FRAPPE_IMAGE_REPO; do
  value="$(fetch_param "${key}")"
  upsert_env "${key}" "${value}"
done

# Optional keys only if present.
for key in APPS_TO_INSTALL DEFAULT_SITE DB_HOST DB_PORT REDIS_CACHE REDIS_QUEUE REDIS_SOCKETIO WORKER_PROCESSES WORKER_QUEUES SITE_REGISTRY_FILE SITE_HEALTH_ENDPOINT; do
  if aws ssm get-parameter --region "${AWS_REGION}" --name "${PARAMETER_PATH}/${key}" >/dev/null 2>&1; then
    value="$(fetch_param "${key}")"
    upsert_env "${key}" "${value}"
  fi
done

echo "Rendered ${ENV_FILE} from SSM parameters under ${PARAMETER_PATH}"
