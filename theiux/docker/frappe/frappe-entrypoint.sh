#!/usr/bin/env bash
set -euo pipefail

ROLE="${1:-backend}"
BENCH_DIR="${BENCH_DIR:-/home/frappe/frappe-bench}"
SITES_DIR="${SITES_DIR:-${BENCH_DIR}/sites}"
FRAPPE_GIT_URL="${FRAPPE_GIT_URL:-https://github.com/frappe/frappe}"
FRAPPE_VERSION="${FRAPPE_VERSION:-version-15}"
APPS_JSON_BASE64="${APPS_JSON_BASE64:-}"

DB_HOST="${DB_HOST:-mariadb}"
DB_PORT="${DB_PORT:-3306}"
REDIS_CACHE="${REDIS_CACHE:-redis://redis-cache:6379/0}"
REDIS_QUEUE="${REDIS_QUEUE:-redis://redis-queue:6379/1}"
REDIS_SOCKETIO="${REDIS_SOCKETIO:-redis://redis-queue:6379/2}"
SOCKETIO_PORT="${SOCKETIO_PORT:-9000}"
FRAPPE_PORT="${FRAPPE_PORT:-8000}"
FRAPPE_USER="${FRAPPE_USER:-frappe}"
AUTO_CREATE_SITE="${AUTO_CREATE_SITE:-true}"
DEFAULT_SITE="${DEFAULT_SITE:-roguesingh.cloud}"
ADMIN_PASSWORD="${ADMIN_PASSWORD:-admin}"
MYSQL_ROOT_PASSWORD="${MYSQL_ROOT_PASSWORD:-}"
UPDATE_FRAPPE_ON_START="${UPDATE_FRAPPE_ON_START:-false}"
APPS_TO_INSTALL="${APPS_TO_INSTALL:-frappe}"
SITE_REGISTRY_FILE="${SITE_REGISTRY_FILE:-sites-enabled.csv}"
WORKER_PROCESSES="${WORKER_PROCESSES:-2}"
WORKER_QUEUES="${WORKER_QUEUES:-short,default,long}"
ENABLE_DEDICATED_SITE_WORKERS="${ENABLE_DEDICATED_SITE_WORKERS:-false}"
DEDICATED_SITE_WORKERS="${DEDICATED_SITE_WORKERS:-}"
WORKER_SITE_ISOLATION_MODE="${WORKER_SITE_ISOLATION_MODE:-shared}"
TENANT_QUEUE_MODE="${TENANT_QUEUE_MODE:-shared}"

mkdir -p "${SITES_DIR}" "${BENCH_DIR}/logs"
touch "${SITES_DIR}/${SITE_REGISTRY_FILE}"

if [ "$(id -u)" -eq 0 ]; then
  # Avoid expensive full bench chown on every boot.
  chown -R "${FRAPPE_USER}:${FRAPPE_USER}" "${SITES_DIR}" "${BENCH_DIR}/logs"
fi

run_as_frappe() {
  if [ "$(id -u)" -eq 0 ]; then
    gosu "${FRAPPE_USER}" "$@"
  else
    "$@"
  fi
}

register_site() {
  local domain="$1"
  if ! run_as_frappe bash -lc "grep -qE '^${domain},${domain}$' '${SITES_DIR}/${SITE_REGISTRY_FILE}'"; then
    run_as_frappe bash -lc "echo '${domain},${domain}' >> '${SITES_DIR}/${SITE_REGISTRY_FILE}'"
  fi
}

if [ ! -d "${BENCH_DIR}/apps/frappe" ]; then
  echo "Bench missing at ${BENCH_DIR}. Image may be corrupted." >&2
  exit 1
fi

cd "${BENCH_DIR}"

# Allow users to dynamically pin any frappe upstream repo + ref.
if [ -d "${BENCH_DIR}/apps/frappe/.git" ]; then
  if [ "${UPDATE_FRAPPE_ON_START}" = "true" ]; then
    if run_as_frappe git -C "${BENCH_DIR}/apps/frappe" remote get-url origin >/dev/null 2>&1; then
      run_as_frappe git -C "${BENCH_DIR}/apps/frappe" remote set-url origin "${FRAPPE_GIT_URL}" || true
    else
      run_as_frappe git -C "${BENCH_DIR}/apps/frappe" remote add origin "${FRAPPE_GIT_URL}" || true
    fi

    if run_as_frappe git -C "${BENCH_DIR}/apps/frappe" fetch --tags --prune origin >/dev/null 2>&1; then
      if run_as_frappe git -C "${BENCH_DIR}/apps/frappe" rev-parse --verify "origin/${FRAPPE_VERSION}" >/dev/null 2>&1; then
        run_as_frappe git -C "${BENCH_DIR}/apps/frappe" checkout -B "${FRAPPE_VERSION}" "origin/${FRAPPE_VERSION}" || true
      else
        run_as_frappe git -C "${BENCH_DIR}/apps/frappe" checkout "${FRAPPE_VERSION}" || true
      fi
    fi
  fi
fi

# Apps should be built into the image in CI/CD.
if [ -n "${APPS_JSON_BASE64}" ]; then
  echo "APPS_JSON_BASE64 is set at runtime; ignored. Build apps into image during CI." >&2
fi

run_as_frappe bash -lc "cat > '${SITES_DIR}/common_site_config.json' <<EOF
{
  \"db_host\": \"${DB_HOST}\",
  \"db_port\": ${DB_PORT},
  \"redis_cache\": \"${REDIS_CACHE}\",
  \"redis_queue\": \"${REDIS_QUEUE}\",
  \"redis_socketio\": \"${REDIS_SOCKETIO}\",
  \"socketio_port\": ${SOCKETIO_PORT},
  \"dns_multitenant\": true,
  \"limits\": {
    \"max_users\": 1000
  }
}
EOF"

# Best-effort wait for dependencies to avoid crash loops during restart.
wait-for-it -t 60 "${DB_HOST}:${DB_PORT}" || true

# First boot helper: create a site if none exists.
if [ "${ROLE}" = "backend" ] && [ "${AUTO_CREATE_SITE}" = "true" ] && [ -z "$(ls -1 "${SITES_DIR}"/*/site_config.json 2>/dev/null || true)" ]; then
  if [ -z "${MYSQL_ROOT_PASSWORD}" ]; then
    echo "MYSQL_ROOT_PASSWORD is required for AUTO_CREATE_SITE=true" >&2
    exit 1
  fi

  run_as_frappe bash -lc "cd '${BENCH_DIR}' && bench new-site '${DEFAULT_SITE}' \
    --db-root-username root \
    --db-root-password '${MYSQL_ROOT_PASSWORD}' \
    --admin-password '${ADMIN_PASSWORD}' \
    --no-mariadb-socket \
    --set-default"
  register_site "${DEFAULT_SITE}"
fi

if [ "${ROLE}" = "backend" ] && [ -n "${APPS_TO_INSTALL}" ]; then
  target_site="${DEFAULT_SITE}"
  if [ -f "${SITES_DIR}/currentsite.txt" ]; then
    target_site="$(cat "${SITES_DIR}/currentsite.txt")"
  fi
  for app in $(echo "${APPS_TO_INSTALL}" | tr ',' ' '); do
    if ! run_as_frappe bash -lc "cd '${BENCH_DIR}' && bench --site '${target_site}' list-apps | grep -qx '${app}'"; then
      echo "Installing app ${app} on ${target_site}"
      run_as_frappe bash -lc "cd '${BENCH_DIR}' && bench --site '${target_site}' install-app '${app}'"
    fi
  done
fi

case "${ROLE}" in
  backend)
    if [ "$(id -u)" -eq 0 ]; then
      exec gosu "${FRAPPE_USER}" bash -lc "cd '${BENCH_DIR}' && bench --site all serve --port '${FRAPPE_PORT}'"
    else
      exec bash -lc "cd '${BENCH_DIR}' && bench --site all serve --port '${FRAPPE_PORT}'"
    fi
    ;;
  worker)
    run_as_frappe bash -lc "cd '${BENCH_DIR}' && \
      if [ '${WORKER_SITE_ISOLATION_MODE}' = 'shared' ] || [ '${ENABLE_DEDICATED_SITE_WORKERS}' != 'true' ]; then \
        i=1; \
        while [ \"\$i\" -lt \"${WORKER_PROCESSES}\" ]; do \
          bench worker --queue '${WORKER_QUEUES}' & \
          i=\$((i+1)); \
        done; \
        exec bench worker --queue '${WORKER_QUEUES}'; \
      fi; \
      for site in \$(echo '${DEDICATED_SITE_WORKERS}' | tr ',' ' '); do \
        if [ -n \"\$site\" ]; then \
          if [ '${TENANT_QUEUE_MODE}' = 'namespaced' ]; then \
            site_queues=\"\$(echo '${WORKER_QUEUES}' | awk -v s=\"\$site\" -F',' '{for(i=1;i<=NF;i++){gsub(/^ +| +$/, \"\", \$i); if(length(\$i)>0){printf \"%s%s:%s\", (c++?\",\":\"\"), s, \$i}}}')\"; \
          else \
            site_queues='${WORKER_QUEUES}'; \
          fi; \
          bench worker --site \"\$site\" --queue \"\$site_queues\" & \
        fi; \
      done; \
      exec sleep infinity"
    ;;
  scheduler)
    if [ "$(id -u)" -eq 0 ]; then
      exec gosu "${FRAPPE_USER}" bash -lc "cd '${BENCH_DIR}' && bench schedule"
    else
      exec bash -lc "cd '${BENCH_DIR}' && bench schedule"
    fi
    ;;
  websocket)
    if [ "$(id -u)" -eq 0 ]; then
      exec gosu "${FRAPPE_USER}" bash -lc "cd '${BENCH_DIR}' && node apps/frappe/socketio.js"
    else
      exec bash -lc "cd '${BENCH_DIR}' && node apps/frappe/socketio.js"
    fi
    ;;
  site-manager)
    if [ "$(id -u)" -eq 0 ]; then
      exec gosu "${FRAPPE_USER}" bash -lc "while true; do sleep 3600; done"
    else
      exec bash -lc "while true; do sleep 3600; done"
    fi
    ;;
  *)
    echo "Unsupported role: ${ROLE}" >&2
    exit 1
    ;;
esac
