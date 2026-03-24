#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="${PROJECT_ROOT:-/opt/theiux}"
cd "${PROJECT_ROOT}"

if [ ! -f ".env" ]; then
  echo "FAIL: .env file missing at ${PROJECT_ROOT}"
  exit 1
fi

set -a
source .env
set +a

SITE_REGISTRY_FILE="${SITE_REGISTRY_FILE:-sites-enabled.csv}"
BENCH_DIR="${BENCH_DIR:-/home/frappe/frappe-bench}"
MAX_DEPLOY_MEMORY_PERCENT="${MAX_DEPLOY_MEMORY_PERCENT:-80}"
MIN_DISK_FREE_PERCENT="${MIN_DISK_FREE_PERCENT:-15}"
TENANT_DB_MAX_USER_CONNECTIONS="${TENANT_DB_MAX_USER_CONNECTIONS:-15}"

fails=0
warnings=0
passes=0

pass() {
  passes=$((passes + 1))
  echo "PASS: $*"
}

warn() {
  warnings=$((warnings + 1))
  echo "WARN: $*"
}

fail() {
  fails=$((fails + 1))
  echo "FAIL: $*"
}

value_equals() {
  local actual="$1"
  local expected="$2"
  if [ "${actual}" = "${expected}" ]; then
    return 0
  fi
  return 1
}

to_mib() {
  local raw="$1"
  local value unit
  value="$(echo "${raw}" | sed -E 's/^([0-9.]+)([A-Za-z]+)$/\1/')"
  unit="$(echo "${raw}" | sed -E 's/^([0-9.]+)([A-Za-z]+)$/\2/')"
  case "${unit}" in
    KiB) awk "BEGIN {printf \"%.2f\", ${value}/1024}" ;;
    MiB) awk "BEGIN {printf \"%.2f\", ${value}}" ;;
    GiB) awk "BEGIN {printf \"%.2f\", ${value}*1024}" ;;
    B) awk "BEGIN {printf \"%.2f\", ${value}/1024/1024}" ;;
    *) echo "0" ;;
  esac
}

db_exec() {
  local sql="$1"
  if docker compose exec -T mariadb mariadb -N -uroot -p"${MYSQL_ROOT_PASSWORD}" -e "${sql}" >/tmp/theiux-db.out 2>/tmp/theiux-db.err; then
    cat /tmp/theiux-db.out
    return 0
  fi
  if docker compose exec -T mariadb mariadb -N -u"${MYSQL_USER}" -p"${MYSQL_PASSWORD}" -e "${sql}" >/tmp/theiux-db.out 2>/tmp/theiux-db.err; then
    cat /tmp/theiux-db.out
    return 0
  fi
  return 1
}

echo "== Runtime Validation =="

# 1) Container state and health.
required_services="frappe worker scheduler websocket nginx certbot mariadb redis-cache redis-queue"
for svc in ${required_services}; do
  container_id="$(docker compose ps -q "${svc}" 2>/dev/null || true)"
  if [ -z "${container_id}" ]; then
    fail "Service '${svc}' is not running"
    continue
  fi
  state="$(docker inspect -f '{{.State.Status}}' "${container_id}" 2>/dev/null || true)"
  health="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "${container_id}" 2>/dev/null || true)"
  if [ "${state}" != "running" ]; then
    fail "Service '${svc}' not running (state=${state})"
    continue
  fi
  if [ "${health}" != "none" ] && [ "${health}" != "healthy" ]; then
    if [ "${health}" = "starting" ]; then
      tries=0
      while [ "${tries}" -lt 6 ]; do
        sleep 2
        health="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "${container_id}" 2>/dev/null || true)"
        [ "${health}" = "healthy" ] && break
        tries=$((tries + 1))
      done
    fi
    if [ "${health}" != "none" ] && [ "${health}" != "healthy" ]; then
      fail "Service '${svc}' unhealthy (${health})"
      continue
    fi
  fi
  pass "Service '${svc}' running (health=${health})"
done

# 2) Redis cache checks.
cache_maxmemory="$(docker compose exec -T redis-cache redis-cli CONFIG GET maxmemory | awk 'NR==2{print $1}' || true)"
cache_policy="$(docker compose exec -T redis-cache redis-cli CONFIG GET maxmemory-policy | awk 'NR==2{print $1}' || true)"
if [ -n "${cache_maxmemory}" ] && [ "${cache_maxmemory}" -gt 0 ]; then
  pass "redis-cache maxmemory set (${cache_maxmemory} bytes)"
else
  fail "redis-cache maxmemory is missing or zero"
fi
if value_equals "${cache_policy}" "allkeys-lru"; then
  pass "redis-cache eviction policy is allkeys-lru"
else
  fail "redis-cache eviction policy expected allkeys-lru, got '${cache_policy}'"
fi

# 3) Redis queue durability checks.
queue_aof="$(docker compose exec -T redis-queue redis-cli CONFIG GET appendonly | awk 'NR==2{print $1}' || true)"
queue_policy="$(docker compose exec -T redis-queue redis-cli CONFIG GET maxmemory-policy | awk 'NR==2{print $1}' || true)"
if value_equals "${queue_aof}" "yes"; then
  pass "redis-queue appendonly is enabled"
else
  fail "redis-queue appendonly expected yes, got '${queue_aof}'"
fi
if value_equals "${queue_policy}" "noeviction"; then
  pass "redis-queue eviction policy is noeviction"
else
  fail "redis-queue eviction policy expected noeviction, got '${queue_policy}'"
fi

# 4) MariaDB global config sanity.
db_max_connections="$(db_exec "SHOW VARIABLES LIKE 'max_connections';" | awk '{print $2}' || true)"
db_buffer_pool="$(db_exec "SHOW VARIABLES LIKE 'innodb_buffer_pool_size';" | awk '{print $2}' || true)"
if [ -n "${db_max_connections}" ] && [ "${db_max_connections}" -ge 120 ] && [ "${db_max_connections}" -le 300 ]; then
  pass "MariaDB max_connections sane (${db_max_connections})"
else
  fail "MariaDB global inspection failed or max_connections out of range (120-300). Check MYSQL_ROOT_PASSWORD/MYSQL_USER creds in .env."
fi
if [ -n "${db_buffer_pool}" ] && [ "${db_buffer_pool}" -ge 268435456 ] && [ "${db_buffer_pool}" -le 1073741824 ]; then
  pass "MariaDB innodb_buffer_pool_size sane (${db_buffer_pool} bytes)"
else
  fail "MariaDB global inspection failed or innodb_buffer_pool_size out of range (256MB-1GB)."
fi

# 5) Per-tenant MAX_USER_CONNECTIONS verification.
domains="$(docker compose exec -T frappe bash -lc "cd '${BENCH_DIR}' && if [ -f 'sites/${SITE_REGISTRY_FILE}' ]; then awk -F',' 'NF>=1 && \$1 !~ /^#/ && length(\$1)>0 {print \$1}' 'sites/${SITE_REGISTRY_FILE}'; fi" || true)"
if [ -z "${domains}" ]; then
  warn "No domains found in site registry; skipped per-tenant DB fairness checks"
else
  while IFS= read -r domain; do
    [ -z "${domain}" ] && continue
    db_user="$(docker compose exec -T frappe bash -lc "cd '${BENCH_DIR}' && jq -r '.db_name // empty' 'sites/${domain}/site_config.json'" || true)"
    if [ -z "${db_user}" ]; then
      fail "Could not resolve db_name for tenant '${domain}'"
      continue
    fi
    max_user_conn="$(db_exec "SELECT MAX_USER_CONNECTIONS FROM mysql.user WHERE User='${db_user}' AND Host='%' LIMIT 1;" | awk 'NR==1{print $1}' || true)"
    if [ -z "${max_user_conn}" ]; then
      fail "MAX_USER_CONNECTIONS check failed for tenant '${domain}' (missing privilege to inspect mysql.user or user not found)"
    elif [ "${max_user_conn}" -le "${TENANT_DB_MAX_USER_CONNECTIONS}" ] && [ "${max_user_conn}" -gt 0 ]; then
      pass "Tenant '${domain}' DB fairness cap applied (${max_user_conn})"
    else
      fail "Tenant '${domain}' MAX_USER_CONNECTIONS expected <= ${TENANT_DB_MAX_USER_CONNECTIONS}, got ${max_user_conn}"
    fi
  done <<EOF
${domains}
EOF
fi

# 6) Host memory and disk safety.
mem_total_kb="$(awk '/MemTotal/ {print $2}' /proc/meminfo)"
mem_avail_kb="$(awk '/MemAvailable/ {print $2}' /proc/meminfo)"
mem_used_pct="$(((mem_total_kb - mem_avail_kb) * 100 / mem_total_kb))"
container_mem_mib="$(docker stats --no-stream --format '{{.MemUsage}}' | awk -F'/' '{gsub(/^ +| +$/, "", $1); print $1}' | while read -r m; do echo "$(to_mib "${m}")"; done | awk '{s+=$1} END{printf "%.0f", s}')"
host_mem_total_mib="$((mem_total_kb / 1024))"
platform_mem_pct=$((container_mem_mib * 100 / host_mem_total_mib))
if [ "${platform_mem_pct}" -lt 75 ]; then
  pass "Platform container memory footprint safe (${platform_mem_pct}% of host RAM)"
else
  fail "Platform container memory footprint high (${platform_mem_pct}% >= 75%)"
fi
if [ "${mem_used_pct}" -lt "${MAX_DEPLOY_MEMORY_PERCENT}" ]; then
  pass "Host memory usage safe (${mem_used_pct}% < ${MAX_DEPLOY_MEMORY_PERCENT}%)"
else
  warn "Host memory usage high (${mem_used_pct}% >= ${MAX_DEPLOY_MEMORY_PERCENT}%) likely due to non-platform processes"
fi

disk_free_pct="$(df -P "${PROJECT_ROOT}" | awk 'NR==2{gsub("%","",$5); print 100-$5}')"
if [ "${disk_free_pct}" -ge "${MIN_DISK_FREE_PERCENT}" ]; then
  pass "Disk free space safe (${disk_free_pct}% >= ${MIN_DISK_FREE_PERCENT}%)"
else
  fail "Disk free space low (${disk_free_pct}% < ${MIN_DISK_FREE_PERCENT}%)"
fi

echo "== Validation Summary =="
echo "passes=${passes} warnings=${warnings} fails=${fails}"
if [ "${fails}" -gt 0 ]; then
  echo "RESULT: FAIL"
  exit 1
fi
echo "RESULT: PASS"
