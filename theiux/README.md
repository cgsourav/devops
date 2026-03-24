# theiux Multi-Tenant Frappe Hosting Platform

`theiux` extends the existing AWS + EC2 + Docker + NGINX + Certbot + CI/CD architecture into a pooled multi-tenant platform.

## Architecture (Text Diagram)

```text
                    +----------------------------+
                    |         Route53 DNS        |
                    +-------------+--------------+
                                  |
                           many tenant domains
                                  |
                         +--------v--------+
                         | NGINX + Certbot |
                         | host header TLS |
                         +--------+--------+
                                  |
                    +-------------v--------------+
                    |   Frappe bench containers  |
                    |  backend / websocket       |
                    |  worker pool / scheduler   |
                    +-------------+--------------+
                                  |
             +--------------------+--------------------+
             |                                         |
      +------v-------+                          +------v-------+
      | Shared Redis |                          | Shared MariaDB|
      | cache/queue  |                          | multi-schema  |
      +--------------+                          +---------------+
             |
      +------v-----------------------------------------------+
      | shared sites volume (site folders + backups + files) |
      +---------------------------+---------------------------+
                                  |
                              S3 backup
```

## Core Multi-Tenant Model

- One bench hosts many sites.
- Shared DB and Redis are configured in `sites/common_site_config.json`.
- Site isolation is at:
  - DB schema level (one DB per site)
  - Site directory level (`sites/<domain>`)
- Shared workers/scheduler reduce per-site cost.

## What Changed

- `docker-compose.yml`
  - keeps EC2 + Compose architecture
  - switches to one shared Redis service (`redis`)
  - tunes MariaDB for pooled workloads
  - keeps shared Frappe worker model
- `docker/frappe/frappe-entrypoint.sh`
  - writes multi-tenant `common_site_config.json`
  - enables DNS multi-tenancy
  - supports worker pool via `WORKER_PROCESSES` and `WORKER_QUEUES`
  - maintains site registry file for routing/SSL
- `scripts/site-lifecycle.sh` (new)
  - automates site onboarding and removal
  - no manual `bench new-site` / `bench install-app` from operators
- `docker/nginx/start-nginx.sh`
  - dynamically reads routed domains from site registry
  - safe NGINX reload behavior on mode transitions
- `docker/certbot/renew.sh`
  - auto-expands cert SAN list from current domains
  - no manual certbot commands required
- `bin/theiux`
  - adds `deploy-site`, `list-sites`, `remove-site` commands over SSM

## Runtime Commands

### Platform lifecycle

```bash
./bin/theiux init
./bin/theiux deploy <app>
./bin/theiux rollback <app>
./bin/theiux destroy <app>
```

### Tenant lifecycle (fully automated)

```bash
./bin/theiux deploy-site --domain site1.example.com --apps frappe,erpnext
./bin/theiux list-sites
./bin/theiux remove-site --domain site1.example.com --drop-db
```

Operator-safe local equivalent on node:

```bash
PROJECT_ROOT=/opt/theiux scripts/site-lifecycle.sh deploy-site --domain site1.example.com --apps frappe
```

## Site Provisioning Flow (`deploy-site`)

1. Creates site schema and site directory
2. Installs apps for that site
3. Registers domain in site registry (`sites/sites-enabled.csv`)
4. Updates `SITE_HOSTS` in `.env`
5. Reloads NGINX + Certbot services
6. Runs health check (`/api/method/ping`)

## NGINX and Domain Routing

- Routing is host-header based.
- Domain list is generated dynamically from the site registry.
- No manual NGINX conf edits for new tenants.
- Safe reload is handled by the startup watcher loop.

## SSL Automation

- Certbot uses webroot challenge.
- Certificate SAN set is continuously reconciled from current domain registry.
- Renew loop runs automatically and persists in `letsencrypt` volume.
- New domains added through `deploy-site` are picked up automatically.

## Storage and Backups

- Shared persistent volumes:
  - `sites`
  - `logs`
  - `mariadb-data`
  - `letsencrypt`
- Backups:
  - per-site backups via `bench backup --with-files`
  - full DB dump + volume archives
  - upload to S3 with `scripts/backup-and-sync.sh`

## Cost Optimization Strategy

### Phase 1 (3-5 sites, single node)

- Instance: `t3.medium`
- Shared services and workers
- Expected lower unit cost than single-tenant EC2 model

### Phase 2 (5-10 sites, single node)

- Increase `WORKER_PROCESSES` carefully
- Tune MariaDB memory and connection limits
- Monitor queue latency and DB CPU

### Phase 3 (horizontal scaling)

- Add additional EC2 nodes with same stack
- Move DB to RDS
- Move Redis to ElastiCache
- Add load balancer in front of NGINX nodes

## Resource Governance

- Worker concurrency controlled via:
  - `WORKER_PROCESSES`
  - `WORKER_QUEUES`
- Queue sharing prevents per-site worker duplication.
- Keep concurrency conservative to avoid site starvation.

## Required Environment Variables

See `.env.example`; key multi-tenant variables:

- `SITE_HOSTS`
- `SITE_REGISTRY_FILE` (default `sites-enabled.csv`)
- `REDIS_CACHE`, `REDIS_QUEUE`, `REDIS_SOCKETIO` (single Redis DB indexes)
- `WORKER_PROCESSES`, `WORKER_QUEUES`
- `HEALTHCHECK_HOST`, `HEALTHCHECK_URL`

## Validation Checklist

Use this for acceptance testing:

1. Deploy stack on one EC2 node (`--profile internal-db --profile internal-redis`)
2. Run `deploy-site` for 3 domains
3. Verify each domain serves correct site
4. Verify HTTPS is issued and valid
5. Verify no manual bench command is needed by operator
6. Run moderate concurrent traffic and check worker queue stability

## Production Hardening

- **Tenant protection**: host+IP rate limiting and connection caps in NGINX templates.
- **Worker isolation modes**:
  - shared (`WORKER_SITE_ISOLATION_MODE=shared`)
  - optional dedicated-site workers (`ENABLE_DEDICATED_SITE_WORKERS=true`, `DEDICATED_SITE_WORKERS=siteA,siteB`)
- **Health dashboard**:
  - `./bin/theiux health`
  - `./bin/theiux health site <domain>`
- **Site-scoped logs**:
  - `./bin/theiux logs --site <domain> --since 15m`
- **Safe restore**:
  - `./bin/theiux restore-site --domain <domain> --backup-file /opt/theiux/backups/<ts>/...sql.gz`
- **Retention**:
  - local backup pruning via `SITE_BACKUP_RETENTION_DAYS`

## Compatibility Notes

- Preserves current EC2-based deployment model
- Preserves Docker/Compose runtime
- Preserves NGINX + Certbot edge strategy
- Preserves CI/CD with ECR image deployment
- Extends existing architecture instead of replacing it
# theiux Fully Automated AWS Frappe Platform

`theiux` is upgraded to a no-SSH, Terraform + SSM deployment platform with:

- Terraform-provisioned AWS infrastructure (EC2/EIP/SG/IAM/S3/ECR/Route53 optional)
- GitHub Actions CI/CD push-to-deploy
- SSM-based deployment execution (auditable, no SSH key)
- Blue/Green deployment with NGINX traffic switch
- Automatic rollback on deploy health failure
- Automatic SSL (Certbot issue/renew + NGINX auto-reload)
- Auto Frappe site creation and app installation
- Centralized CloudWatch container logs
- CLI lifecycle commands (`theiux init|deploy|rollback|destroy`)

## Project Layout

```text
theiux/
├── .github/workflows/deploy.yml
├── bin/theiux
├── docker/
│   ├── certbot/renew.sh
│   ├── frappe/
│   │   ├── Dockerfile
│   │   └── frappe-entrypoint.sh
│   └── nginx/
├── docker-compose.yml
├── scripts/
│   ├── deploy.sh
│   ├── rollback.sh
│   ├── render-env-from-ssm.sh
│   └── ssm-deploy.sh
└── terraform/
    ├── main.tf
    ├── outputs.tf
    ├── user_data.sh.tftpl
    ├── variables.tf
    └── versions.tf
```

## End-to-End Flow

1. Developer pushes code to `main`.
2. GitHub Actions builds image and pushes to ECR.
3. Workflow sends SSM Run Command to EC2 (no SSH).
4. Instance pulls latest code, renders `.env` from Parameter Store, and deploys.
5. Blue/Green traffic shifts only after health check passes.
6. If health check fails, automatic rollback restores previous routing and image tag.

## Prerequisites

- Terraform >= 1.5
- AWS CLI configured
- AWS account permissions for EC2/IAM/ECR/S3/SSM/Route53/CloudWatch
- GitHub OIDC role configured and set in repo secret `AWS_ROLE_ARN`

## 1) Infrastructure Provisioning

Create `terraform/terraform.tfvars`:

```hcl
aws_region      = "us-east-1"
project_name    = "theiux"
environment     = "prod"
repo_url        = "https://github.com/your-org/theiux.git"
repo_ref        = "main"
deploy_path     = "/opt/theiux"
route53_zone_id = "Z1234567890"
root_domain     = "example.com"
subdomain       = "app"
```

Run:

```bash
./bin/theiux init
```

Terraform provisions:

- EC2 instance
- Elastic IP
- Security Group (80/443 only, no SSH ingress)
- IAM Role + Instance Profile
- S3 bucket
- ECR repository
- Route53 record (if domain vars provided)
- CloudWatch log group

## 2) Secrets and Runtime Config (SSM Parameter Store)

Set parameters under `/${project_name}/${environment}` (default: `/theiux/prod`):

- `SITE_HOSTS`
- `PRIMARY_DOMAIN`
- `CERTBOT_EMAIL`
- `MYSQL_ROOT_PASSWORD`
- `MYSQL_PASSWORD`
- `ADMIN_PASSWORD`
- `HEALTHCHECK_HOST`
- `HEALTHCHECK_URL`
- `FRAPPE_IMAGE_REPO`

Optional:

- `APPS_TO_INSTALL`
- `DEFAULT_SITE`
- `DB_HOST`, `DB_PORT`
- `REDIS_CACHE`, `REDIS_QUEUE`, `REDIS_SOCKETIO`

`scripts/render-env-from-ssm.sh` materializes `.env` during deployment.

## 3) GitHub Actions (No SSH)

Repo variables:

- `AWS_REGION`
- `ECR_REPOSITORY`
- `EC2_INSTANCE_ID`
- `EC2_DEPLOY_PATH`
- `SSM_PARAMETER_PATH`
- `PYTHON_VERSION` (optional)
- `NODE_VERSION` (optional)
- `WKHTMLTOPDF_VERSION` (optional)
- `APPS_JSON_BASE64` (optional)

Repo secrets:

- `AWS_ROLE_ARN`
- `GH_APP_SOURCE_PAT` (optional for private app sources)

Workflow deployment is executed with AWS SSM Run Command only.

## 4) Blue/Green Deployment and Rollback

`scripts/deploy.sh`:

- deploys to inactive color stack (`blue`/`green`)
- runs migrations on the target stack
- switches `ACTIVE_COLOR` and reloads edge
- verifies health
- rolls back traffic and image on failure

Manual rollback command:

```bash
./bin/theiux rollback myapp
```

## 5) SSL and DNS Automation

- Certbot auto-issues certs for domains in `SITE_HOSTS`
- Certbot renewal loop runs continuously
- NGINX auto-switches HTTP -> HTTPS when cert appears
- Route53 DNS A record is provisioned by Terraform (if configured)

No manual certbot commands are required.

## 6) Frappe Automation

`docker/frappe/frappe-entrypoint.sh` now supports:

- automatic first-site creation (`AUTO_CREATE_SITE=true`)
- automatic app installation via `APPS_TO_INSTALL`
- automatic `common_site_config.json` generation

No manual `bench new-site` or `bench install-app` is required for standard boot.

## 7) CloudWatch Logging

`docker-compose.yml` configures `awslogs` for all containers:

- `awslogs-region`: `AWS_REGION`
- `awslogs-group`: `CLOUDWATCH_LOG_GROUP` (default `/theiux/prod/containers`)
- stream names by service/color

Logs are viewable in CloudWatch without SSH access.

## 8) CLI Commands

```bash
./bin/theiux init
./bin/theiux deploy myapp
./bin/theiux rollback myapp
./bin/theiux destroy myapp
```

## 9) Idempotency and Security

- Terraform applies are idempotent for infrastructure.
- Deploys are rerunnable and converge on desired image/color.
- Secrets are sourced from Parameter Store, not repository files.
- SSH-based deployment is removed from CI path.
# theiux Production Frappe Platform

Production-grade, Docker-based CI/CD infrastructure for Frappe with AWS ECR + EC2 deployment, automated TLS, and backup/S3 integration.

## Folder Structure

```text
theiux/
├── .github/workflows/deploy.yml
├── docker/
│   ├── certbot/renew.sh
│   ├── frappe/
│   │   ├── Dockerfile
│   │   └── frappe-entrypoint.sh
│   └── nginx/nginx.conf.template
├── docker-compose.yml
├── .env.example
├── scripts/
│   ├── backup-and-sync.sh
│   ├── deploy.sh
│   └── ec2-bootstrap.sh
└── README.md
```

## Architecture

- `frappe`: backend HTTP app server (`bench serve`)
- `websocket`: Socket.IO process (`node apps/frappe/socketio.js`)
- `worker`: async queues (`short,default,long`)
- `scheduler`: cron/event scheduler
- `nginx`: reverse proxy + TLS termination + static serving + websocket proxy
- `certbot`: Let’s Encrypt issue + renew loop
- `mariadb`: internal DB (optional, can switch to external RDS)
- `redis-cache`, `redis-queue`, `redis-socketio`: internal Redis (optional, can switch to ElastiCache)

## Quickstart (One Command)

### A) Single app (Frappe core only)

```bash
cp .env.example .env
# edit .env (at least: AWS_REGION, PRIMARY_DOMAIN, CERTBOT_EMAIL, passwords)
bash scripts/provision-and-deploy.sh
```

### B) Multiple apps (public/private repos)

Create `apps.json` (example):

```json
[
  {
    "url": "https://github.com/frappe/frappe",
    "branch": "version-15"
  },
  {
    "url": "https://github.com/your-org/your-private-app",
    "branch": "main"
  }
]
```

Deploy:

```bash
cp .env.example .env
APPS_JSON_FILE=./apps.json bash scripts/provision-and-deploy.sh --yes
```

For private GitHub repos, use tokenized HTTPS URLs in `apps.json` or configure CI-based ECR build with BuildKit secrets.

### Destroy created AWS resources

```bash
bash scripts/destroy.sh --yes
```

`destroy.sh` reads `.aws-provision-state.json` and removes the EC2 instance, SG, IAM role/profile, key pair, and managed EIP/S3 artifact bucket.

## 1) Configure Environment

```bash
cp .env.example .env
```

Update `.env` with:
- domains (`SITE_HOSTS`, `PRIMARY_DOMAIN`)
- SSL email (`CERTBOT_EMAIL`)
- Frappe source/version (`FRAPPE_GIT_URL`, `FRAPPE_VERSION`)
- DB/Redis endpoints (internal or external)
- ECR repo (`FRAPPE_IMAGE_REPO`)
- AWS + S3 backup values

## 2) Build Locally (optional)

```bash
docker build \
  --build-arg PYTHON_VERSION=3.11 \
  --build-arg NODE_VERSION=20 \
  --build-arg WKHTMLTOPDF_VERSION=0.12.6.1-3 \
  -f docker/frappe/Dockerfile \
  -t theiux-frappe:local \
  .
```

## 3) Start Stack on EC2

For internal DB/Redis:

```bash
docker compose --profile internal-db --profile internal-redis up -d
```

For external RDS/ElastiCache, keep `DB_HOST` and `REDIS_*` pointing to managed services and run without those profiles.

## 4) First Site Creation (inside container)

```bash
docker compose exec frappe bench new-site yoursite.example.com
docker compose exec frappe bench --site yoursite.example.com install-app frappe
```

For multisite:
- keep multiple site folders under `sites/`
- configure DNS entries in `SITE_HOSTS`

## 5) SSL Automation

- NGINX serves ACME challenge on `/.well-known/acme-challenge/`
- NGINX starts in HTTP mode automatically if cert is missing
- Once cert appears, NGINX auto-reloads to HTTPS mode and HTTP redirects to HTTPS
- Certbot container:
  - issues initial cert if missing
  - runs continuous renew loop
- certs live in Docker volume `letsencrypt` and survive restarts

## 5.1) Elastic IP + DNS Automation

You can automate EIP association and optional Route53 record updates during bootstrap:

```bash
REPO_URL="git@github.com:your-org/theiux.git" \
DEPLOY_PATH="/opt/theiux" \
RUN_EIP_SETUP=true \
AWS_REGION="us-east-1" \
DOMAIN_NAME="roguesingh.cloud" \
HOSTED_ZONE_ID="Z1234567890" \
bash scripts/ec2-bootstrap.sh
```

Script behavior:
- associates existing `EIP_ALLOCATION_ID` if provided
- otherwise allocates a new EIP when `AUTO_ALLOCATE_EIP=true`
- optionally UPSERTs `A` records for root and `www` in Route53

## 6) CI/CD (GitHub Actions)

On push to `main`:
1. Build image with dynamic build args (`PYTHON_VERSION`, `NODE_VERSION`, `WKHTMLTOPDF_VERSION`)
2. Push to ECR tagged with commit SHA
3. SSH to EC2
4. Update `IMAGE_TAG`
5. Pull + restart via `scripts/deploy.sh`
6. Run `bench migrate` for all discovered sites
7. Recreate bench services (`frappe`, `worker`, `scheduler`, `websocket`) cleanly
8. Health-check + automatic rollback to previous image if failure

Required repository variables/secrets:

- **Variables**
  - `AWS_REGION`
  - `ECR_REPOSITORY`
  - `PYTHON_VERSION`
  - `NODE_VERSION`
  - `WKHTMLTOPDF_VERSION`
  - `APPS_JSON_BASE64` (optional: base64-encoded apps manifest)
- **Secrets**
  - `AWS_ROLE_ARN`
  - `EC2_HOST`
  - `EC2_USER`
  - `EC2_SSH_PRIVATE_KEY`
  - `EC2_DEPLOY_PATH`
  - `GH_APP_SOURCE_PAT` (optional for private app repos in apps manifest)

## 7) EC2 Bootstrap

```bash
REPO_URL="git@github.com:your-org/theiux.git" \
DEPLOY_PATH="/opt/theiux" \
bash scripts/ec2-bootstrap.sh
```

This script installs Docker, Compose plugin, AWS CLI, clones repo, and initializes `.env`.

## 7.1) Provision Script Variables

`scripts/provision-and-deploy.sh` reads from `.env` and supports:
- `INSTANCE_TYPE` (default `t3.small`)
- `ROOT_VOLUME_SIZE_GB` (default `40`)
- `SSH_CIDR` (default `0.0.0.0/0`)
- `APP_USER` (default `ubuntu`)
- `LOCAL_IMAGE_REPO` (default `theiux-frappe`)
- `USE_INTERNAL_DB` / `USE_INTERNAL_REDIS` (`true`/`false`)
- `APPS_JSON_FILE` (env at runtime, optional)

Flags:
- `--dry-run`: prints planned AWS/SSH actions only (no mutation)
- `--yes`: skips interactive confirmation
- `--no-reuse`: force new stack creation even if state has a live instance

Idempotent behavior:
- by default the script reuses an existing running/pending/stopped instance from `.aws-provision-state.json`
- to replace with a fresh stack, run `bash scripts/destroy.sh --yes` first or use `--no-reuse`

## 8) Backup + S3 Sync

```bash
PROJECT_ROOT=/opt/theiux bash scripts/backup-and-sync.sh
```

What it does:
- full MariaDB dump
- archives `sites` and `logs` Docker volumes
- uploads artifacts to S3 backup bucket
- optional continuous site file sync to dedicated S3 bucket

Recommended cron:

```cron
0 2 * * * PROJECT_ROOT=/opt/theiux /bin/bash /opt/theiux/scripts/backup-and-sync.sh >> /var/log/theiux-backup.log 2>&1
```

## 9) Security Notes

- No secrets are hardcoded in code
- `.env` is runtime contract and should be managed securely
- Use IAM roles on EC2 (avoid static AWS keys)
- Ready to replace `.env` values with AWS Secrets Manager injection in deployment step

## 10) Scalability Path

- Move `mariadb` to RDS (set `DB_HOST`, disable internal-db profile)
- Move Redis to ElastiCache (set `REDIS_*`, disable internal-redis profile)
- Current service split maps directly to ECS tasks or Kubernetes deployments
- NGINX can be replaced by ALB + ingress in future EKS migration

## Bonus Notes

- **Rollback-safe deploy**: included (`scripts/deploy.sh`)
- **Health checks**: included in Compose and deploy script
- **Minimal downtime**: Compose service recreation + health validation (no full stack outage)
- **Blue/Green (future)**: can be implemented by running parallel compose projects (`theiux-blue` / `theiux-green`) behind a shared load balancer

## Dynamic Frappe/App Versioning

- `FRAPPE_GIT_URL` and `FRAPPE_VERSION` let you pin Frappe to any upstream and ref (branch/tag/commit).
- `APPS_JSON_BASE64` is consumed at build-time in CI to bake apps into the image (immutable deploy). Generate from `apps.json`:

```bash
base64 -w0 apps.json
```

Example `apps.json`:

```json
[
  {
    "url": "https://github.com/frappe/frappe",
    "branch": "version-15"
  },
  {
    "url": "https://github.com/your-org/your-custom-app",
    "branch": "main"
  }
]
```

For private GitHub app repos, set repo secret `GH_APP_SOURCE_PAT`. CI passes it as a BuildKit secret so app sources can be fetched during image build.
