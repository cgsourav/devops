#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="${PROJECT_ROOT:-/opt/theiux}"
cd "${PROJECT_ROOT}"

if [ ! -f .env ]; then
  echo ".env missing" >&2
  exit 1
fi

if [ ! -s .previous_image_tag ]; then
  echo "No previous image tag available." >&2
  exit 1
fi

current_color="$(awk -F= '/^ACTIVE_COLOR=/{print $2}' .env || true)"
current_color="${current_color:-blue}"
if [ "${current_color}" = "blue" ]; then
  rollback_color="green"
else
  rollback_color="blue"
fi

rollback_tag="$(cat .previous_image_tag)"
if grep -q '^IMAGE_TAG=' .env; then
  sed -i "s/^IMAGE_TAG=.*/IMAGE_TAG=${rollback_tag}/" .env
else
  echo "IMAGE_TAG=${rollback_tag}" >> .env
fi

if grep -q '^ACTIVE_COLOR=' .env; then
  sed -i "s/^ACTIVE_COLOR=.*/ACTIVE_COLOR=${rollback_color}/" .env
else
  echo "ACTIVE_COLOR=${rollback_color}" >> .env
fi

STACK_COLOR="${rollback_color}" docker compose -p "theiux-${rollback_color}" up -d --remove-orphans frappe worker scheduler websocket
docker compose up -d nginx certbot
STACK_COLOR="${current_color}" docker compose -p "theiux-${current_color}" down || true

echo "Rollback completed: image=${rollback_tag}, color=${rollback_color}"
