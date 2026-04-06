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
SITE_RATE_LIMIT_RPS="${SITE_RATE_LIMIT_RPS:-20}"
SITE_RATE_LIMIT_BURST="${SITE_RATE_LIMIT_BURST:-40}"
SITE_CONN_LIMIT="${SITE_CONN_LIMIT:-30}"
SITE_ISOLATION_MODE="${WORKER_SITE_ISOLATION_MODE:-shared}"
TENANT_QUEUE_MODE="${TENANT_QUEUE_MODE:-shared}"
TENANT_DB_MAX_USER_CONNECTIONS="${TENANT_DB_MAX_USER_CONNECTIONS:-15}"

usage() {
  cat <<'EOF'
Usage:
  scripts/site-lifecycle.sh deploy-site --domain <domain> [--apps app1,app2] [--git-repo <url>] [--admin-password xxx]
  scripts/site-lifecycle.sh list-sites
  scripts/site-lifecycle.sh remove-site --domain <domain> [--drop-db]
  scripts/site-lifecycle.sh inventory-bench
  scripts/site-lifecycle.sh inventory-site --domain <domain>
  scripts/site-lifecycle.sh get-app-only --git-repo <url> [--branch <name>]
  scripts/site-lifecycle.sh install-app-on-site --domain <d> --app <name> [--git-repo <url>]
  scripts/site-lifecycle.sh uninstall-app-from-site --domain <d> --app <name>
EOF
}

require_domain() {
  if [ -z "${domain:-}" ]; then
    echo "--domain is required" >&2
    exit 1
  fi
}

# Best-effort app folder name from git URL (used to skip redundant bench get-app on redeploy).
app_name_from_git_repo() {
  local repo="${1:-}"
  repo="${repo%.git}"
  repo="${repo%/}"
  if [[ "${repo}" =~ ^[^:]+@[^:]+:(.+)$ ]]; then
    repo="${BASH_REMATCH[1]}"
  fi
  basename "$(echo "${repo}" | tr '/' '\n' | tail -1)"
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

write_site_policy() {
  compose_exec "
    set -euo pipefail
    cd '${BENCH_DIR}'
    mkdir -p 'sites/${domain}'
    cat > 'sites/${domain}/tenant-policy.json' <<EOF
{
  \"site\": \"${domain}\",
  \"worker_mode\": \"${SITE_ISOLATION_MODE}\",
  \"queue_mode\": \"${TENANT_QUEUE_MODE}\",
  \"worker_queues\": \"${WORKER_QUEUES:-short,default,long}\",
  \"rate_limit_rps\": ${SITE_RATE_LIMIT_RPS},
  \"rate_limit_burst\": ${SITE_RATE_LIMIT_BURST},
  \"concurrent_connection_limit\": ${SITE_CONN_LIMIT}
}
EOF
    bench --site '${domain}' set-config -g rate_limit_rps '${SITE_RATE_LIMIT_RPS}' >/dev/null
    bench --site '${domain}' set-config -g rate_limit_burst '${SITE_RATE_LIMIT_BURST}' >/dev/null
    bench --site '${domain}' set-config -g connection_limit '${SITE_CONN_LIMIT}' >/dev/null
  "
}

enforce_tenant_db_fairness() {
  compose_exec "
    set -euo pipefail
    cd '${BENCH_DIR}'
    db_name=\$(jq -r '.db_name // empty' 'sites/${domain}/site_config.json')
    if [ -z \"\$db_name\" ]; then
      echo 'Unable to resolve db_name for ${domain}' >&2
      exit 1
    fi
    mysql -h '${DB_HOST}' -P '${DB_PORT}' -u root -p'${MYSQL_ROOT_PASSWORD}' <<SQL
ALTER USER '\${db_name}'@'%' WITH MAX_USER_CONNECTIONS ${TENANT_DB_MAX_USER_CONNECTIONS};
ALTER USER '\${db_name}'@'localhost' WITH MAX_USER_CONNECTIONS ${TENANT_DB_MAX_USER_CONNECTIONS};
SQL
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
    git_repo=""
    while [ $# -gt 0 ]; do
      case "$1" in
        --domain) domain="${2:-}"; shift 2 ;;
        --apps) apps="${2:-}"; shift 2 ;;
        --admin-password) admin_password="${2:-}"; shift 2 ;;
        --git-repo) git_repo="${2:-}"; shift 2 ;;
        *) echo "Unknown option: $1" >&2; usage; exit 1 ;;
      esac
    done
    require_domain

    if [ -n "${THEIUX_RUNTIME:-}" ] || [ -n "${THEIUX_RUNTIME_VERSION:-}" ]; then
      echo "[theiux] runtime=${THEIUX_RUNTIME:-unset}:${THEIUX_RUNTIME_VERSION:-unset}" >&2
    fi

    if [ -n "${git_repo}" ]; then
      _app_name="$(app_name_from_git_repo "${git_repo}")"
      compose_exec "
        set -euo pipefail
        cd '${BENCH_DIR}'
        if [ -n \"${_app_name}\" ] && [ -d \"apps/${_app_name}\" ]; then
          echo \"[theiux] app source already present at apps/${_app_name}, skipping bench get-app\" >&2
        else
          bench get-app '${git_repo}'
        fi
      "
    fi

    compose_exec "
      set -euo pipefail
      cd '${BENCH_DIR}'
      if [ -f 'sites/${domain}/site_config.json' ]; then
        echo \"[theiux] site ${domain} already exists, skipping bench new-site\" >&2
      else
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
    write_site_policy
    enforce_tenant_db_fairness
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

  inventory-bench)
    compose_exec "
      set -euo pipefail
      cd '${BENCH_DIR}'
      for d in apps/*/; do
        [ -d \"\${d}\" ] || continue
        n=\$(basename \"\${d}\")
        if [ \"\${n}\" = 'frappe' ]; then
          continue
        fi
        if [ -d \"\${d}/.git\" ]; then
          br=\$(git -C \"\${d}\" rev-parse --abbrev-ref HEAD 2>/dev/null || echo unknown)
          sha=\$(git -C \"\${d}\" rev-parse --short HEAD 2>/dev/null || echo '')
          msg=\$(git -C \"\${d}\" log -1 --pretty=%s 2>/dev/null | head -c 500 || echo '')
          printf 'source|%s|%s|%s|%s\n' \"\${n}\" \"\${br}\" \"\${sha}\" \"\${msg}\"
        fi
      done
    "
    ;;

  inventory-site)
    domain=""
    while [ $# -gt 0 ]; do
      case "$1" in
        --domain) domain="${2:-}"; shift 2 ;;
        *) echo "Unknown option: $1" >&2; usage; exit 1 ;;
      esac
    done
    require_domain
    compose_exec "
      set -euo pipefail
      cd '${BENCH_DIR}'
      bench --site '${domain}' list-apps 2>/dev/null | while IFS= read -r line; do
        line=\$(echo \"\${line}\" | sed 's/^[[:space:]]*//;s/[[:space:]]*\$//')
        [ -z \"\${line}\" ] && continue
        case \"\${line}\" in
          '*'*) continue ;;
        esac
        printf 'installed|%s\n' \"\${line}\"
      done
    "
    ;;

  get-app-only)
    git_repo=""
    git_branch=""
    while [ $# -gt 0 ]; do
      case "$1" in
        --git-repo) git_repo="${2:-}"; shift 2 ;;
        --branch) git_branch="${2:-}"; shift 2 ;;
        *) echo "Unknown option: $1" >&2; usage; exit 1 ;;
      esac
    done
    if [ -z "${git_repo}" ]; then
      echo "--git-repo is required" >&2
      exit 1
    fi
    if [ -n "${git_branch}" ]; then
      compose_exec "
      set -euo pipefail
      cd '${BENCH_DIR}'
      bench get-app '${git_repo}' --branch '${git_branch}'
    "
    else
      compose_exec "
      set -euo pipefail
      cd '${BENCH_DIR}'
      bench get-app '${git_repo}'
    "
    fi
    ;;

  install-app-on-site)
    domain=""
    app_name=""
    git_repo=""
    while [ $# -gt 0 ]; do
      case "$1" in
        --domain) domain="${2:-}"; shift 2 ;;
        --app) app_name="${2:-}"; shift 2 ;;
        --git-repo) git_repo="${2:-}"; shift 2 ;;
        *) echo "Unknown option: $1" >&2; usage; exit 1 ;;
      esac
    done
    require_domain
    if [ -z "${app_name}" ]; then
      echo "--app is required" >&2
      exit 1
    fi
    compose_exec "
      set -euo pipefail
      cd '${BENCH_DIR}'
      if [ ! -d \"apps/${app_name}\" ]; then
        if [ -z '${git_repo}' ]; then
          echo 'app not present on bench and no --git-repo provided' >&2
          exit 1
        fi
        bench get-app '${git_repo}'
      fi
      bench --site '${domain}' install-app '${app_name}'
    "
    ;;

  uninstall-app-from-site)
    domain=""
    app_name=""
    while [ $# -gt 0 ]; do
      case "$1" in
        --domain) domain="${2:-}"; shift 2 ;;
        --app) app_name="${2:-}"; shift 2 ;;
        *) echo "Unknown option: $1" >&2; usage; exit 1 ;;
      esac
    done
    require_domain
    if [ -z "${app_name}" ]; then
      echo "--app is required" >&2
      exit 1
    fi
    if [ "${app_name}" = 'frappe' ]; then
      echo 'refusing to uninstall frappe' >&2
      exit 1
    fi
    compose_exec "
      set -euo pipefail
      cd '${BENCH_DIR}'
      bench --site '${domain}' uninstall-app '${app_name}' --yes --no-backup || bench --site '${domain}' uninstall-app '${app_name}' --yes
    "
    ;;

  *)
    usage
    exit 1
    ;;
esac
