#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="${PROJECT_ROOT:-/opt/theiux}"
cd "${PROJECT_ROOT}"

if [ ! -f ".env" ]; then
  echo ".env file is missing in ${PROJECT_ROOT}" >&2
  exit 1
fi

set -a
source .env
set +a

SITE_REGISTRY_FILE="${SITE_REGISTRY_FILE:-sites-enabled.csv}"
BENCH_DIR="${BENCH_DIR:-/home/frappe/frappe-bench}"
HEALTH_ENDPOINT="${SITE_HEALTH_ENDPOINT:-/api/method/ping}"
FRAPPE_SERVICE="${FRAPPE_SERVICE:-frappe}"
NGINX_SERVICE="${NGINX_SERVICE:-nginx}"
CERTBOT_SERVICE="${CERTBOT_SERVICE:-certbot}"

usage() {
  cat <<'EOF'
Usage:
  scripts/site-lifecycle.sh deploy-site --domain <domain> [--apps app1,app2] [--admin-password xxx]
  scripts/site-lifecycle.sh list-sites
  scripts/site-lifecycle.sh remove-site --domain <domain> [--drop-db]
EOF
}

require_domain() {
  if [ -z "${domain:-}" ]; then
    echo "--domain is required" >&2
    exit 1
  fi
}

compose_exec() {
  docker compose exec -T "${FRAPPE_SERVICE}" bash -lc "$1"
}

upsert_site_registry() {
  compose_exec "
    set -euo pipefail
    cd '${BENCH_DIR}'
    mkdir -p sites
    touch 'sites/${SITE_REGISTRY_FILE}'
    grep -qE '^${domain},${domain}\$' 'sites/${SITE_REGISTRY_FILE}' || echo '${domain},${domain}' >> 'sites/${SITE_REGISTRY_FILE}'
  "
}

remove_site_registry() {
  compose_exec "
    set -euo pipefail
    cd '${BENCH_DIR}'
    touch 'sites/${SITE_REGISTRY_FILE}'
    awk -F',' '\$1 != \"${domain}\"' 'sites/${SITE_REGISTRY_FILE}' > 'sites/${SITE_REGISTRY_FILE}.tmp'
    mv 'sites/${SITE_REGISTRY_FILE}.tmp' 'sites/${SITE_REGISTRY_FILE}'
  "
}

refresh_site_hosts_env() {
  domains="$(compose_exec "cd '${BENCH_DIR}' && if [ -f 'sites/${SITE_REGISTRY_FILE}' ]; then awk -F',' 'NF >= 1 && \$1 !~ /^#/ && length(\$1) > 0 {print \$1}' 'sites/${SITE_REGISTRY_FILE}' | tr '\n' ',' | sed 's/,\$//'; fi")"
  if [ -n "${domains}" ]; then
    if grep -q '^SITE_HOSTS=' .env; then
      sed -i "s|^SITE_HOSTS=.*|SITE_HOSTS=${domains}|" .env
    else
      echo "SITE_HOSTS=${domains}" >> .env
    fi
  fi
}

reload_edge() {
  docker compose up -d "${NGINX_SERVICE}" "${CERTBOT_SERVICE}" >/dev/null
}

validate_health() {
  curl -fsS --max-time 10 -H "Host: ${domain}" "http://127.0.0.1${HEALTH_ENDPOINT}" >/dev/null
}

command="${1:-}"
shift || true

case "${command}" in
  deploy-site)
    domain=""
    apps="${APPS_TO_INSTALL:-frappe}"
    admin_password="${ADMIN_PASSWORD:-admin}"
    while [ $# -gt 0 ]; do
      case "$1" in
        --domain) domain="${2:-}"; shift 2 ;;
        --apps) apps="${2:-}"; shift 2 ;;
        --admin-password) admin_password="${2:-}"; shift 2 ;;
        *) echo "Unknown option: $1" >&2; usage; exit 1 ;;
      esac
    done
    require_domain

    compose_exec "
      set -euo pipefail
      cd '${BENCH_DIR}'
      if [ ! -f 'sites/${domain}/site_config.json' ]; then
        bench new-site '${domain}' \
          --db-root-username root \
          --db-root-password '${MYSQL_ROOT_PASSWORD}' \
          --admin-password '${admin_password}' \
          --no-mariadb-socket
      fi
    "

    for app in $(echo "${apps}" | tr ',' ' '); do
      compose_exec "
        set -euo pipefail
        cd '${BENCH_DIR}'
        if ! bench --site '${domain}' list-apps | grep -qx '${app}' >/dev/null 2>&1; then
          bench --site '${domain}' install-app '${app}'
        fi
      "
    done

    upsert_site_registry
    refresh_site_hosts_env
    reload_edge
    validate_health
    echo "Site deployed successfully: ${domain}"
    ;;

  list-sites)
    compose_exec "
      set -euo pipefail
      cd '${BENCH_DIR}'
      if [ -f 'sites/${SITE_REGISTRY_FILE}' ]; then
        awk -F',' 'NF >= 2 && \$1 !~ /^#/ {printf \"domain=%s site=%s\\n\", \$1, \$2}' 'sites/${SITE_REGISTRY_FILE}'
      fi
    "
    ;;

  remove-site)
    domain=""
    drop_db="false"
    while [ $# -gt 0 ]; do
      case "$1" in
        --domain) domain="${2:-}"; shift 2 ;;
        --drop-db) drop_db="true"; shift 1 ;;
        *) echo "Unknown option: $1" >&2; usage; exit 1 ;;
      esac
    done
    require_domain
    remove_site_registry
    if [ "${drop_db}" = "true" ]; then
      compose_exec "cd '${BENCH_DIR}' && bench drop-site '${domain}' --root-username root --root-password '${MYSQL_ROOT_PASSWORD}' --force"
    else
      compose_exec "cd '${BENCH_DIR}' && rm -rf 'sites/${domain}'"
    fi
    refresh_site_hosts_env
    reload_edge
    echo "Site removed: ${domain}"
    ;;

  *)
    usage
    exit 1
    ;;
esac
