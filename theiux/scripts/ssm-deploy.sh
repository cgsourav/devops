#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="${PROJECT_ROOT:-/opt/theiux}"
AWS_REGION="${AWS_REGION:-us-east-1}"
PARAMETER_PATH="${PARAMETER_PATH:-/theiux/prod}"
IMAGE_TAG="${1:-}"
GIT_REF="${GIT_REF:-main}"

if [ -z "${IMAGE_TAG}" ]; then
  echo "Usage: $0 <image_tag>" >&2
  exit 1
fi

cd "${PROJECT_ROOT}"
git fetch --all --prune
git checkout "${GIT_REF}"
git reset --hard "origin/${GIT_REF}" || true

chmod +x scripts/*.sh
PROJECT_ROOT="${PROJECT_ROOT}" AWS_REGION="${AWS_REGION}" PARAMETER_PATH="${PARAMETER_PATH}" scripts/render-env-from-ssm.sh
docker compose --profile internal-db --profile internal-redis up -d mariadb redis-cache redis-queue redis-socketio nginx certbot
PROJECT_ROOT="${PROJECT_ROOT}" scripts/deploy.sh "${IMAGE_TAG}"
