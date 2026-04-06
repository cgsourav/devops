#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="${PROJECT_ROOT:-/opt/theiux}"
cd "${PROJECT_ROOT}"

if [ ! -f ".env" ]; then
  echo ".env file is missing in ${PROJECT_ROOT}" >&2
  exit 1
fi

echo "Pre-deploy validation across all registered sites..."
PROJECT_ROOT="${PROJECT_ROOT}" REQUIRE_ALL_HEALTHY=true scripts/site-health.sh summary

NEW_IMAGE_TAG="${1:-}"
if [ -z "${NEW_IMAGE_TAG}" ]; then
  echo "Usage: $0 <image_tag>" >&2
  exit 1
fi

memory_used_percent() {
  total_kb="$(awk '/MemTotal/ {print $2}' /proc/meminfo)"
  avail_kb="$(awk '/MemAvailable/ {print $2}' /proc/meminfo)"
  used_kb=$((total_kb - avail_kb))
  echo $((used_kb * 100 / total_kb))
}

MAX_DEPLOY_MEMORY_PERCENT="$(awk -F= '/^MAX_DEPLOY_MEMORY_PERCENT=/{print $2}' .env || true)"
MAX_DEPLOY_MEMORY_PERCENT="${MAX_DEPLOY_MEMORY_PERCENT:-80}"

current_mem="$(memory_used_percent)"
if [ "${current_mem}" -ge "${MAX_DEPLOY_MEMORY_PERCENT}" ]; then
  echo "Refusing deploy: memory at ${current_mem}% exceeds MAX_DEPLOY_MEMORY_PERCENT=${MAX_DEPLOY_MEMORY_PERCENT}%." >&2
  exit 1
fi

echo "Pre-deploy backup checkpoint (bench backup --with-files) across all sites..."
docker compose exec -T frappe bash -lc '
set -euo pipefail
run_as_frappe() {
  if [ "$(id -u)" -eq 0 ]; then
    gosu "${FRAPPE_USER:-frappe}" "$@"
  else
    "$@"
  fi
}
cd "${BENCH_DIR:-/home/frappe/frappe-bench}"
site_count=0
for d in sites/*; do
  site="$(basename "$d")"
  if [ -f "sites/${site}/site_config.json" ]; then
    site_count=$((site_count + 1))
    echo "Backing up ${site} (--with-files)"
    run_as_frappe bench --site "${site}" backup --with-files
  fi
done
if [ "${site_count}" -eq 0 ]; then
  echo "No sites detected for backup checkpoint."
fi
'
echo "Pre-deploy backup checkpoint completed."

old_tag="$(awk -F= '/^IMAGE_TAG=/{print $2}' .env || true)"
if grep -q '^IMAGE_TAG=' .env; then
  sed -i "s/^IMAGE_TAG=.*/IMAGE_TAG=${NEW_IMAGE_TAG}/" .env
else
  echo "IMAGE_TAG=${NEW_IMAGE_TAG}" >> .env
fi

if [ -n "${old_tag}" ]; then
  echo "${old_tag}" > .previous_image_tag
fi

echo "Starting rolling application update..."
docker compose pull frappe worker scheduler websocket
for svc in worker scheduler websocket frappe; do
  echo "Rolling update for ${svc}..."
  docker compose up -d --no-deps "${svc}"
done

# Run migrations for every detected site (site_config.json present).
echo "Running bench migrate on active stack..."
docker compose exec -T frappe bash -lc '
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

echo "Reloading edge and validating health..."
docker compose up -d nginx certbot
docker compose exec -T nginx sh -lc 'nginx -t && nginx -s reload' || true

if ! curl -fsS --max-time 10 -H "Host: ${health_host}" "${health_url}" > /tmp/theiux-health.json; then
  echo "Deployment health check failed, initiating rollback..."
  if [ -s ".previous_image_tag" ]; then
    rollback_tag="$(cat .previous_image_tag)"
    sed -i "s/^IMAGE_TAG=.*/IMAGE_TAG=${rollback_tag}/" .env
    docker compose pull frappe worker scheduler websocket
    for svc in worker scheduler websocket frappe; do
      docker compose up -d --no-deps "${svc}"
    done
    docker compose up -d nginx certbot
    docker compose exec -T nginx sh -lc 'nginx -t && nginx -s reload' || true
  fi
  exit 1
else
  echo "Post-deploy full multi-tenant health verification..."
  if ! PROJECT_ROOT="${PROJECT_ROOT}" REQUIRE_ALL_HEALTHY=true scripts/site-health.sh summary; then
    echo "Post-deploy tenant health verification failed, initiating rollback..."
    if [ -s ".previous_image_tag" ]; then
      rollback_tag="$(cat .previous_image_tag)"
      sed -i "s/^IMAGE_TAG=.*/IMAGE_TAG=${rollback_tag}/" .env
      docker compose pull frappe worker scheduler websocket
      for svc in worker scheduler websocket frappe; do
        docker compose up -d --no-deps "${svc}"
      done
      docker compose up -d nginx certbot
      docker compose exec -T nginx sh -lc 'nginx -t && nginx -s reload' || true
    fi
    exit 1
  fi
  echo "${NEW_IMAGE_TAG}" > .last_successful_image_tag
  if [ -f "${PROJECT_ROOT}/.aws-provision-state.json" ]; then
    echo "Route53 DNS sync (automated)..."
    bash "${PROJECT_ROOT}/scripts/route53-sync-dns.sh" || true
  fi
  echo "Deployment succeeded with image tag ${NEW_IMAGE_TAG}"
fi
