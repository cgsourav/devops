#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="${PROJECT_ROOT:-/opt/theiux}"
cd "${PROJECT_ROOT}"

if [ ! -f ".env" ]; then
  echo ".env file is missing in ${PROJECT_ROOT}" >&2
  exit 1
fi

NEW_IMAGE_TAG="${1:-}"
if [ -z "${NEW_IMAGE_TAG}" ]; then
  echo "Usage: $0 <image_tag>" >&2
  exit 1
fi

ACTIVE_COLOR="$(awk -F= '/^ACTIVE_COLOR=/{print $2}' .env || true)"
ACTIVE_COLOR="${ACTIVE_COLOR:-blue}"
if [ "${ACTIVE_COLOR}" = "blue" ]; then
  TARGET_COLOR="green"
else
  TARGET_COLOR="blue"
fi

old_tag="$(awk -F= '/^IMAGE_TAG=/{print $2}' .env || true)"
if grep -q '^IMAGE_TAG=' .env; then
  sed -i "s/^IMAGE_TAG=.*/IMAGE_TAG=${NEW_IMAGE_TAG}/" .env
else
  echo "IMAGE_TAG=${NEW_IMAGE_TAG}" >> .env
fi

if [ -n "${old_tag}" ]; then
  echo "${old_tag}" > .previous_image_tag
fi

echo "Starting target color stack: ${TARGET_COLOR}"
STACK_COLOR="${TARGET_COLOR}" docker compose -p "theiux-${TARGET_COLOR}" pull frappe worker scheduler websocket
STACK_COLOR="${TARGET_COLOR}" docker compose -p "theiux-${TARGET_COLOR}" up -d --remove-orphans frappe worker scheduler websocket

# Run migrations for every detected site (site_config.json present).
echo "Running bench migrate on ${TARGET_COLOR} stack..."
STACK_COLOR="${TARGET_COLOR}" docker compose -p "theiux-${TARGET_COLOR}" exec -T frappe bash -lc '
set -euo pipefail
run_as_frappe() {
  if [ "$(id -u)" -eq 0 ]; then
    gosu "${FRAPPE_USER:-frappe}" "$@"
  else
    "$@"
  fi
}
cd "${BENCH_DIR:-/home/frappe/frappe-bench}"
for d in sites/*; do
  site="$(basename "$d")"
  if [ -f "sites/${site}/site_config.json" ]; then
    echo "Migrating ${site}"
    run_as_frappe bench --site "${site}" migrate
  fi
done
'

health_host="$(awk -F= '/^HEALTHCHECK_HOST=/{print $2}' .env || true)"
health_host="${health_host:-127.0.0.1}"
health_url="http://127.0.0.1/api/method/ping"
if grep -q '^HEALTHCHECK_URL=' .env; then
  health_url="$(awk -F= '/^HEALTHCHECK_URL=/{print $2}' .env)"
fi

echo "Switching traffic to ${TARGET_COLOR} and validating health..."
if grep -q '^ACTIVE_COLOR=' .env; then
  sed -i "s/^ACTIVE_COLOR=.*/ACTIVE_COLOR=${TARGET_COLOR}/" .env
else
  echo "ACTIVE_COLOR=${TARGET_COLOR}" >> .env
fi
docker compose up -d nginx certbot

if ! curl -fsS --max-time 10 -H "Host: ${health_host}" "${health_url}" > /tmp/theiux-health.json; then
  echo "Deployment health check failed, initiating rollback..."
  if grep -q '^ACTIVE_COLOR=' .env; then
    sed -i "s/^ACTIVE_COLOR=.*/ACTIVE_COLOR=${ACTIVE_COLOR}/" .env
  else
    echo "ACTIVE_COLOR=${ACTIVE_COLOR}" >> .env
  fi
  docker compose up -d nginx certbot
  STACK_COLOR="${TARGET_COLOR}" docker compose -p "theiux-${TARGET_COLOR}" down || true
  if [ -s ".previous_image_tag" ]; then
    sed -i "s/^IMAGE_TAG=.*/IMAGE_TAG=$(cat .previous_image_tag)/" .env
  fi
  exit 1
else
  echo "${NEW_IMAGE_TAG}" > .last_successful_image_tag
  echo "${TARGET_COLOR}" > .last_successful_color
  STACK_COLOR="${ACTIVE_COLOR}" docker compose -p "theiux-${ACTIVE_COLOR}" down || true
  echo "Deployment succeeded with image tag ${NEW_IMAGE_TAG}"
fi
