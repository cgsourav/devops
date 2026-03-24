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

timestamp="$(date +%Y%m%d-%H%M%S)"
backup_dir="${PROJECT_ROOT}/backups/${timestamp}"
mkdir -p "${backup_dir}"

echo "Creating database dump..."
docker compose exec -T mariadb sh -c \
  "mysqldump -uroot -p\"${MYSQL_ROOT_PASSWORD}\" --single-transaction --quick --routines --events --all-databases" \
  > "${backup_dir}/mariadb-all.sql"

echo "Creating per-site backups in shared volume..."
docker compose exec -T frappe bash -lc '
set -euo pipefail
cd "${BENCH_DIR:-/home/frappe/frappe-bench}"
for d in sites/*; do
  site="$(basename "$d")"
  if [ -f "sites/${site}/site_config.json" ]; then
    bench --site "${site}" backup --with-files
  fi
done
'

echo "Archiving sites and logs..."
docker run --rm \
  -v sites:/sites:ro \
  -v logs:/logs:ro \
  -v "${backup_dir}:/backup" \
  alpine:3.20 sh -c "tar -czf /backup/sites.tar.gz -C / sites && tar -czf /backup/logs.tar.gz -C / logs"

if [ -n "${S3_BACKUP_BUCKET:-}" ]; then
  echo "Uploading backup bundle to s3://${S3_BACKUP_BUCKET}/"
  aws s3 cp "${backup_dir}/mariadb-all.sql" "s3://${S3_BACKUP_BUCKET}/${timestamp}/mariadb-all.sql" --region "${AWS_REGION}"
  aws s3 cp "${backup_dir}/sites.tar.gz" "s3://${S3_BACKUP_BUCKET}/${timestamp}/sites.tar.gz" --region "${AWS_REGION}"
  aws s3 cp "${backup_dir}/logs.tar.gz" "s3://${S3_BACKUP_BUCKET}/${timestamp}/logs.tar.gz" --region "${AWS_REGION}"
fi

if [ "${ENABLE_S3_SITE_SYNC:-false}" = "true" ] && [ -n "${S3_SITE_SYNC_BUCKET:-}" ]; then
  echo "Syncing site files to s3://${S3_SITE_SYNC_BUCKET}/"
  docker run --rm \
    -v sites:/sites:ro \
    -v "${HOME}/.aws:/root/.aws:ro" \
    amazon/aws-cli:2.17.19 \
    s3 sync /sites "s3://${S3_SITE_SYNC_BUCKET}/sites/" --region "${AWS_REGION}" --delete
fi

echo "Backup complete at ${backup_dir}"
