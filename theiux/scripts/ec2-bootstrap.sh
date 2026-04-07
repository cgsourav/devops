#!/usr/bin/env bash
set -euo pipefail

# OS user that owns the deploy tree and runs docker compose / bench-related host commands (idempotent with bootstrap-host).
THEIUX_REMOTE_USER="${THEIUX_REMOTE_USER:-${APP_USER:-frappe}}"
DEPLOY_PATH="${DEPLOY_PATH:-/opt/theiux}"
REPO_URL="${REPO_URL:-}"

if [ -z "${REPO_URL}" ]; then
  echo "Set REPO_URL environment variable (git clone URL)." >&2
  exit 1
fi

sudo apt-get update
sudo apt-get install -y ca-certificates curl gnupg lsb-release git unzip jq awscli sudo

if ! command -v docker >/dev/null 2>&1; then
  sudo install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
  sudo chmod a+r /etc/apt/keyrings/docker.gpg
  echo \
    "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
    $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
    sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
  sudo apt-get update
  sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
fi

if ! id -u "${THEIUX_REMOTE_USER}" >/dev/null 2>&1; then
  sudo useradd --create-home --shell /bin/bash "${THEIUX_REMOTE_USER}"
fi
sudo usermod -aG docker "${THEIUX_REMOTE_USER}"
sudo mkdir -p "${DEPLOY_PATH}"
sudo chown -R "${THEIUX_REMOTE_USER}:${THEIUX_REMOTE_USER}" "${DEPLOY_PATH}"

if [ ! -d "${DEPLOY_PATH}/.git" ]; then
  sudo -u "${THEIUX_REMOTE_USER}" -H git clone "${REPO_URL}" "${DEPLOY_PATH}"
else
  sudo -u "${THEIUX_REMOTE_USER}" -H git -C "${DEPLOY_PATH}" fetch --all --prune
fi

if [ ! -f "${DEPLOY_PATH}/.env" ] && [ -f "${DEPLOY_PATH}/.env.example" ]; then
  cp "${DEPLOY_PATH}/.env.example" "${DEPLOY_PATH}/.env"
  echo "Created ${DEPLOY_PATH}/.env. Update values before first deployment."
fi

sudo chmod +x "${DEPLOY_PATH}/scripts/"*.sh 2>/dev/null || true
sudo chmod +x "${DEPLOY_PATH}/theiux/scripts/"*.sh 2>/dev/null || true
sudo chown -R "${THEIUX_REMOTE_USER}:${THEIUX_REMOTE_USER}" "${DEPLOY_PATH}"

if [ "${RUN_EIP_SETUP:-false}" = "true" ]; then
  AWS_REGION="${AWS_REGION:-us-east-1}" \
  EIP_ALLOCATION_ID="${EIP_ALLOCATION_ID:-}" \
  AUTO_ALLOCATE_EIP="${AUTO_ALLOCATE_EIP:-true}" \
  HOSTED_ZONE_ID="${HOSTED_ZONE_ID:-}" \
  DOMAIN_NAME="${DOMAIN_NAME:-}" \
  CREATE_WWW_RECORD="${CREATE_WWW_RECORD:-true}" \
  bash "${DEPLOY_PATH}/scripts/aws-eip-and-dns.sh"
fi

echo "Bootstrap completed. Re-login may be required for docker group membership."
