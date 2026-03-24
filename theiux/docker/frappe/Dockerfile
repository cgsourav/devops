# syntax=docker/dockerfile:1.7
ARG PYTHON_VERSION=3.11
FROM python:${PYTHON_VERSION}-slim-bookworm

ARG NODE_VERSION=20
ARG WKHTMLTOPDF_VERSION=0.12.6.1-3
ARG FRAPPE_BASE_VERSION=version-15
ARG APPS_JSON_BASE64=

ENV DEBIAN_FRONTEND=noninteractive
ENV FRAPPE_USER=frappe
ENV FRAPPE_HOME=/home/frappe
ENV BENCH_DIR=/home/frappe/frappe-bench
ENV PATH=/home/frappe/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    wget \
    ca-certificates \
    gnupg \
    cron \
    procps \
    git \
    mariadb-client \
    redis-tools \
    jq \
    gosu \
    wait-for-it \
    xfonts-75dpi \
    xfonts-base \
    libfontconfig1 \
    libx11-6 \
    libxext6 \
    libxrender1 \
    libjpeg62-turbo \
    libssl3 \
    libpng16-16 \
    libfreetype6 \
    && rm -rf /var/lib/apt/lists/*

# Install Node.js from NodeSource based on build arg.
RUN curl -fsSL "https://deb.nodesource.com/setup_${NODE_VERSION}.x" | bash - \
    && apt-get update && apt-get install -y --no-install-recommends nodejs \
    && npm install -g yarn \
    && rm -rf /var/lib/apt/lists/*

# Install wkhtmltopdf from package release configurable by build arg.
RUN arch="$(dpkg --print-architecture)" \
    && case "$arch" in \
      amd64) wk_arch="amd64" ;; \
      arm64) wk_arch="arm64" ;; \
      *) echo "Unsupported architecture: $arch" && exit 1 ;; \
    esac \
    && wget -O /tmp/wkhtmltox.deb "https://github.com/wkhtmltopdf/packaging/releases/download/${WKHTMLTOPDF_VERSION}/wkhtmltox_${WKHTMLTOPDF_VERSION}.bookworm_${wk_arch}.deb" \
    && apt-get update && apt-get install -y --no-install-recommends /tmp/wkhtmltox.deb \
    && rm -f /tmp/wkhtmltox.deb \
    && rm -rf /var/lib/apt/lists/*

RUN useradd -m -s /bin/bash "${FRAPPE_USER}" \
    && pip install --no-cache-dir "frappe-bench>=5,<6"

# Create a valid bench during image build. Runtime only configures and starts processes.
RUN gosu "${FRAPPE_USER}" bench init \
    --skip-redis-config-generation \
    --frappe-branch "${FRAPPE_BASE_VERSION}" \
    "${BENCH_DIR}"

# Install additional apps at build-time (public/private) so runtime stays immutable.
RUN --mount=type=secret,id=github_pat \
    gosu "${FRAPPE_USER}" bash -lc '\
      if [ -n "${APPS_JSON_BASE64}" ]; then \
        echo "${APPS_JSON_BASE64}" | base64 -d > /tmp/apps.json; \
        if [ -f /run/secrets/github_pat ] && [ -s /run/secrets/github_pat ]; then \
          GITHUB_PAT="$(cat /run/secrets/github_pat)"; \
          git config --global url."https://${GITHUB_PAT}:x-oauth-basic@github.com/".insteadOf "https://github.com/"; \
          git config --global url."https://${GITHUB_PAT}:x-oauth-basic@github.com/".insteadOf "git@github.com:"; \
        fi; \
        cd "${BENCH_DIR}"; \
        bench get-app --resolve-deps --apps_path /tmp/apps.json; \
        bench build; \
        rm -f /tmp/apps.json; \
        git config --global --unset-all url."https://${GITHUB_PAT}:x-oauth-basic@github.com/".insteadOf || true; \
      fi'
WORKDIR ${FRAPPE_HOME}

COPY --chown=${FRAPPE_USER}:${FRAPPE_USER} docker/frappe/frappe-entrypoint.sh /usr/local/bin/frappe-entrypoint.sh
RUN chmod +x /usr/local/bin/frappe-entrypoint.sh

EXPOSE 8000 9000

ENTRYPOINT ["/usr/local/bin/frappe-entrypoint.sh"]
CMD ["backend"]
