#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="${PROJECT_ROOT:-/opt/theiux}"
cd "${PROJECT_ROOT}"

if [ ! -f ".env" ]; then
  echo ".env file missing at ${PROJECT_ROOT}" >&2
  exit 1
fi

set -a
source .env
set +a

BENCH_DIR="${BENCH_DIR:-/home/frappe/frappe-bench}"

domain=""
backup_file=""
while [ $# -gt 0 ]; do
  case "$1" in
    --domain) domain="${2:-}"; shift 2 ;;
    --backup-file) backup_file="${2:-}"; shift 2 ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
done

if [ -z "${domain}" ] || [ -z "${backup_file}" ]; then
  echo "Usage: scripts/site-restore.sh --domain <domain> --backup-file <sql.gz>" >&2
  exit 1
fi

if [ ! -f "${backup_file}" ]; then
  echo "Backup file not found: ${backup_file}" >&2
  exit 1
fi

echo "Restoring site ${domain} from ${backup_file}"
docker compose exec -T frappe bash -lc "
set -euo pipefail
cd '${BENCH_DIR}'
if [ ! -f 'sites/${domain}/site_config.json' ]; then
  bench new-site '${domain}' \
    --db-root-username root \
    --db-root-password '${MYSQL_ROOT_PASSWORD}' \
    --admin-password '${ADMIN_PASSWORD}' \
    --no-mariadb-socket
fi
"

docker compose cp "${backup_file}" "frappe:/tmp/theiux-restore.sql.gz"
docker compose exec -T frappe bash -lc "
set -euo pipefail
cd '${BENCH_DIR}'
bench --site '${domain}' --force restore /tmp/theiux-restore.sql.gz
bench --site '${domain}' migrate
"

echo "Restore complete for ${domain}. Ensure site files are restored from sites archive if needed."
