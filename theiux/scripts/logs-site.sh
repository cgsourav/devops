#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="${PROJECT_ROOT:-/opt/theiux}"
cd "${PROJECT_ROOT}"

if [ $# -lt 2 ]; then
  echo "Usage: scripts/logs-site.sh --site <domain> [--since 10m]" >&2
  exit 1
fi

site=""
since="15m"
while [ $# -gt 0 ]; do
  case "$1" in
    --site) site="${2:-}"; shift 2 ;;
    --since) since="${2:-}"; shift 2 ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
done

if [ -z "${site}" ]; then
  echo "--site is required" >&2
  exit 1
fi

echo "=== nginx access (${site}) ==="
docker compose logs --since "${since}" nginx 2>&1 | rg "\"host\":\"${site}\"|Host: ${site}" || true

echo "=== frappe app (${site}) ==="
docker compose logs --since "${since}" frappe worker scheduler 2>&1 | rg "${site}" || true
