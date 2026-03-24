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

rollback_tag="$(cat .previous_image_tag)"
if grep -q '^IMAGE_TAG=' .env; then
  sed -i "s/^IMAGE_TAG=.*/IMAGE_TAG=${rollback_tag}/" .env
else
  echo "IMAGE_TAG=${rollback_tag}" >> .env
fi

docker compose pull frappe worker scheduler websocket
for svc in worker scheduler websocket frappe; do
  docker compose up -d --no-deps "${svc}"
done
docker compose up -d nginx certbot
docker compose exec -T nginx sh -lc 'nginx -t && nginx -s reload' || true

echo "Rollback completed: image=${rollback_tag}"
