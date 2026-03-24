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
SITE_REGISTRY_FILE="${SITE_REGISTRY_FILE:-sites-enabled.csv}"
HEALTH_ENDPOINT="${SITE_HEALTH_ENDPOINT:-/api/method/ping}"
TIMEOUT_SECONDS="${SITE_HEALTH_TIMEOUT_SECONDS:-6}"
REQUIRE_ALL_HEALTHY="${REQUIRE_ALL_HEALTHY:-true}"

mode="${1:-summary}"
target_domain="${2:-}"

get_domains() {
  docker compose exec -T frappe bash -lc "
    set -euo pipefail
    cd '${BENCH_DIR}'
    if [ -f 'sites/${SITE_REGISTRY_FILE}' ]; then
      awk -F',' 'NF >= 1 && \$1 !~ /^#/ && length(\$1) > 0 {print \$1}' 'sites/${SITE_REGISTRY_FILE}'
    fi
  "
}

check_site() {
  local domain="$1"
  local code
  code="$(curl -sS -o /tmp/theiux-site-health.out -w "%{http_code}" --max-time "${TIMEOUT_SECONDS}" -H "Host: ${domain}" "http://127.0.0.1${HEALTH_ENDPOINT}" || true)"
  if [ "${code}" = "200" ]; then
    echo "healthy ${domain}"
    return 0
  fi
  echo "unhealthy ${domain} http_status=${code:-000}"
  return 1
}

if [ "${mode}" = "site" ]; then
  if [ -z "${target_domain}" ]; then
    echo "Usage: scripts/site-health.sh site <domain>" >&2
    exit 1
  fi
  check_site "${target_domain}"
  exit $?
fi

domains="$(get_domains || true)"
if [ -z "${domains}" ]; then
  echo "No sites found in registry."
  exit 0
fi

ok=0
fail=0
while IFS= read -r domain; do
  if check_site "${domain}"; then
    ok=$((ok + 1))
  else
    fail=$((fail + 1))
  fi
done <<EOF
${domains}
EOF

echo "summary healthy=${ok} unhealthy=${fail}"
if [ "${REQUIRE_ALL_HEALTHY}" = "true" ] && [ "${fail}" -gt 0 ]; then
  exit 1
fi
