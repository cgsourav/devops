FROM python:3.12-slim
WORKDIR /app
ENV PYTHONPATH=/app

# Terraform + AWS CLI: required for `theiux init` (POST /v1/admin/theiux-init) and `aws`/`terraform` on PATH.
RUN apt-get update && apt-get install -y --no-install-recommends curl unzip ca-certificates \
 && ARCH="$(uname -m)" \
 && case "$ARCH" in x86_64) TF_ARCH=amd64;; aarch64) TF_ARCH=arm64;; *) echo "unsupported arch: $ARCH" >&2; exit 1;; esac \
 && TERRAFORM_VERSION=1.10.5 \
 && curl -fsSL "https://releases.hashicorp.com/terraform/${TERRAFORM_VERSION}/terraform_${TERRAFORM_VERSION}_linux_${TF_ARCH}.zip" -o /tmp/tf.zip \
 && unzip -q /tmp/tf.zip -d /usr/local/bin \
 && rm /tmp/tf.zip \
 && apt-get purge -y curl unzip && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload"]
