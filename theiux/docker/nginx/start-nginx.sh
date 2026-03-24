#!/usr/bin/env sh
set -eu

CERT_PATH="/etc/letsencrypt/live/${PRIMARY_DOMAIN}/fullchain.pem"
HTTP_TPL="/etc/nginx/templates/nginx.http.conf.template"
HTTPS_TPL="/etc/nginx/templates/nginx.https.conf.template"
SITE_REGISTRY_FILE="${SITE_REGISTRY_FILE:-sites-enabled.csv}"
SITE_REGISTRY_PATH="/var/www/html/${SITE_REGISTRY_FILE}"

resolve_site_hosts() {
  if [ -f "${SITE_REGISTRY_PATH}" ]; then
    hosts_from_registry="$(awk -F',' 'NF >= 1 && $1 !~ /^#/ && length($1) > 0 {print $1}' "${SITE_REGISTRY_PATH}" | tr '\n' ',' | sed 's/,$//')"
    if [ -n "${hosts_from_registry}" ]; then
      SITE_HOSTS="${hosts_from_registry}"
      export SITE_HOSTS
    fi
  fi
}

render_nginx_conf() {
  resolve_site_hosts
  if [ -f "${CERT_PATH}" ]; then
    envsubst '${ACTIVE_COLOR} ${FRAPPE_BACKEND_PORT} ${FRAPPE_SOCKETIO_PORT} ${SITE_HOSTS} ${PRIMARY_DOMAIN} ${CLIENT_MAX_BODY_SIZE}' < "${HTTPS_TPL}" > /etc/nginx/nginx.conf
  else
    envsubst '${ACTIVE_COLOR} ${FRAPPE_BACKEND_PORT} ${FRAPPE_SOCKETIO_PORT} ${SITE_HOSTS} ${PRIMARY_DOMAIN} ${CLIENT_MAX_BODY_SIZE}' < "${HTTP_TPL}" > /etc/nginx/nginx.conf
  fi
}

resolve_site_hosts
render_nginx_conf
nginx -g 'daemon off;' &
NGINX_PID=$!

if [ -f "${CERT_PATH}" ]; then
  LAST_MODE="https"
else
  LAST_MODE="http"
fi

while true; do
  if [ -f "${CERT_PATH}" ]; then
    CURRENT_MODE="https"
  else
    CURRENT_MODE="http"
  fi

  if [ "${CURRENT_MODE}" != "${LAST_MODE}" ]; then
    render_nginx_conf
    if [ -f /run/nginx.pid ]; then
      nginx -s reload || true
    fi
    LAST_MODE="${CURRENT_MODE}"
  fi

  if ! kill -0 "${NGINX_PID}" 2>/dev/null; then
    exit 1
  fi

  sleep "${NGINX_TEMPLATE_CHECK_INTERVAL_SECONDS:-30}"
done
