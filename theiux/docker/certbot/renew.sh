#!/usr/bin/env sh
set -eu

CERTBOT_EMAIL="${CERTBOT_EMAIL:-}"
PRIMARY_DOMAIN="${PRIMARY_DOMAIN:-}"
SITE_HOSTS="${SITE_HOSTS:-}"
SITE_REGISTRY_FILE="${SITE_REGISTRY_FILE:-sites-enabled.csv}"
SITE_REGISTRY_PATH="/var/www/sites/${SITE_REGISTRY_FILE}"

if [ -z "${PRIMARY_DOMAIN}" ] || [ -z "${SITE_HOSTS}" ] || [ -z "${CERTBOT_EMAIL}" ]; then
  echo "PRIMARY_DOMAIN, SITE_HOSTS, and CERTBOT_EMAIL must be set."
  exit 1
fi

build_domain_args() {
  hosts="${SITE_HOSTS}"
  if [ -f "${SITE_REGISTRY_PATH}" ]; then
    registry_hosts="$(awk -F',' 'NF >= 1 && $1 !~ /^#/ && length($1) > 0 {print $1}' "${SITE_REGISTRY_PATH}" | tr '\n' ',' | sed 's/,$//')"
    if [ -n "${registry_hosts}" ]; then
      hosts="${registry_hosts}"
    fi
  fi
  domain_args=""
  for domain in $(echo "${hosts}" | tr ',' ' '); do
    domain_args="${domain_args} -d ${domain}"
  done
  echo "${domain_args}"
}

if [ ! -f "/etc/letsencrypt/live/${PRIMARY_DOMAIN}/fullchain.pem" ]; then
  domain_args="$(build_domain_args)"
  if ! certbot certonly \
    --webroot \
    --webroot-path /var/www/certbot \
    --email "${CERTBOT_EMAIL}" \
    --agree-tos \
    --no-eff-email \
    --cert-name "${PRIMARY_DOMAIN}" \
    ${domain_args}; then
    echo "Initial certificate issuance failed. Will retry in loop."
  fi
fi

while true; do
  domain_args="$(build_domain_args)"
  certbot renew --webroot --webroot-path /var/www/certbot --quiet || true
  if ! certbot certonly \
    --webroot \
    --webroot-path /var/www/certbot \
    --email "${CERTBOT_EMAIL}" \
    --agree-tos \
    --no-eff-email \
    --cert-name "${PRIMARY_DOMAIN}" \
    --expand \
    ${domain_args}; then
    echo "Certificate ensure/expand failed; continuing retry loop."
  fi
  if [ ! -f "/etc/letsencrypt/live/${PRIMARY_DOMAIN}/fullchain.pem" ]; then
    certbot certonly \
      --webroot \
      --webroot-path /var/www/certbot \
      --email "${CERTBOT_EMAIL}" \
      --agree-tos \
      --no-eff-email \
      --cert-name "${PRIMARY_DOMAIN}" \
      ${domain_args} || true
  fi
  sleep "${CERTBOT_RENEW_INTERVAL_SECONDS:-43200}"
done
