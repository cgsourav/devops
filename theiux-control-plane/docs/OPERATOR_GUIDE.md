# Operator guide: hosting the Theiux control plane

This document is for **platform operators**—engineers and teams who **deploy, configure, and run** the Theiux control plane so that **your customers or internal users** can deploy Frappe applications through the web UI and API.

**New install?** Follow **[SETUP.md](./SETUP.md)** first (env files, AWS credentials in Docker, ports, platform init). This guide assumes the stack is running and focuses on **what each piece does**, **configuration reference**, and **production** concerns.

If you only need to **use** an already-running instance to deploy your own app, see **[End-user deployment guide](./END_USER_DEPLOYMENT_GUIDE.md)** instead.

---

## What you are operating

The control plane consists of:

| Component | Role |
|-----------|------|
| **Backend** (FastAPI) | REST API (`/v1`), auth, deployments, logs |
| **Worker** (RQ) | Runs deployment jobs; invokes the **`theiux`** CLI |
| **PostgreSQL** | Apps, deployments, jobs, sites, users |
| **Redis** | Job queue and worker coordination |
| **Frontend** (Next.js) | Web UI for registration, apps, deploys, logs |
| **`theiux` CLI** (on worker host) | Real deploys via AWS SSM to your Frappe/bench host |

Deployments are **not simulated**: the worker runs **`theiux deploy-site`** with validated arguments and streams logs back into the database.

The SaaS surface includes:

- Tenant/team management (`/v1/team`, `/v1/team/invite`)
- Subscription and plan binding (`/v1/billing/subscription`, `/v1/billing/subscription/select-plan`)
- Site lifecycle operations for domains/SSL and backups/restore

---

## Prerequisites

- **Docker** and **Docker Compose** (or a compatible runtime) on the machine(s) that will run the stack.
- A **clone of this repository** and a **clone of the `theiux`** repository (automation scripts and `bin/theiux`) on paths that Compose can mount.
- **Network path** from the **worker** container to wherever **`theiux`** expects to run (typically the same mount as in development: `../theiux` → `/theiux` inside the container).
- **AWS** credentials available **inside** the **backend** (for Terraform / UI platform init) and **worker** (for **`aws ssm`**), and infrastructure provisioned with **`theiux init`** so **`bin/.theiux-context`** exists. See **[SETUP.md](./SETUP.md)** for mounts, **`AWS_PROFILE`**, and **`TF_VAR_*`** / UI fields.

---

## Quick start (development)

Full checklist: **[SETUP.md](./SETUP.md)**. Minimal commands:

```bash
cp backend/.env.example backend/.env
cp frontend/.env.example frontend/.env.local
# Edit JWT_SECRET, NEXT_PUBLIC_API_BASE_URL=http://localhost:8001
# ~/.aws is mounted by default in docker-compose.yml; set AWS_PROFILE in backend/.env

docker compose up --build
```

- **API**: `http://localhost:8001` — OpenAPI at **`/docs`**, health at **`GET /health`** or **`GET /v1/health`**.
- **UI**: `http://localhost:3001` (default Compose port mapping).
- **Platform init (UI):** **`/admin/theiux-init`** — **`POST /v1/admin/theiux-init`** with JSON body (`aws_region`, `repo_url`, optional Terraform fields). Roles **`admin`** or **`owner`** only. Requires Terraform + AWS CLI in the **backend** image and **AWS credentials in the backend container** (see SETUP). Default registration uses **`owner`**; restrict signups or use **`viewer`** for non-operators if needed.

The Compose file mounts **`../theiux` → `/theiux`** on the backend and worker. Adjust paths in **`docker-compose.yml`** if your `theiux` checkout lives elsewhere; set **`THEIUX_CLI_PATH`** (default **`/theiux/bin/theiux`**).

---

## Before deployments work: `theiux init` and AWS

A deploy runs **`theiux deploy-site`** inside the **worker** container. That CLI refuses to run until **`bin/.theiux-context`** exists:

```text
Run 'theiux init' first.
```

**Create the context file** in one of two ways (details in **[SETUP.md](./SETUP.md)**):

1. **UI:** Sign in as **`admin`** or **`owner`**, open **`/admin/theiux-init`**, enter **AWS region** and **Git repo URL** (and optional Terraform fields), run init. The **backend** container runs Terraform; **`~/.aws`** is mounted by default—set **`AWS_PROFILE`** (or keys) in **`backend/.env`**.

2. **Host CLI:** Install [Terraform](https://www.terraform.io/) and [AWS CLI](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html) on the host, configure credentials, then from the **`theiux`** repo (same path as **`../theiux`** in Compose):
   ```bash
   export TF_VAR_aws_region=your-region
   export TF_VAR_repo_url=https://github.com/org/repo.git
   ./bin/theiux init
   ```

**Verify** on the host:

```bash
test -f /path/to/theiux/bin/.theiux-context && echo OK
```

Restart **`docker compose`** so the **worker** sees **`/theiux/bin/.theiux-context`**.

**Mounts:** The **worker** uses **`../theiux:/theiux:ro`** (read-only). The **backend** uses a **read-write** mount so UI init can write **`bin/.theiux-context`**. The file must appear on the host at the mounted path.

**AWS inside the worker:** The `theiux` script calls **`aws ssm`**. Compose mounts **`~/.aws`** on the worker; set **`AWS_PROFILE`** in **`backend/.env`** (shared via **`env_file`**) or set **`AWS_ACCESS_KEY_ID`** / **`AWS_SECRET_ACCESS_KEY`**.

### Bootstrap deploy for ERP Lab (operator CLI)

End users normally use the **home page** wizard (**Use ERP Lab template** or **Start ERP Lab deploy wizard**). To enqueue the same pipeline from the host (e.g. right after creating a user), run:

```bash
docker compose exec backend python -m app.cli enqueue-curated-app --preset erp_lab --email user@example.com
```

This matches **`POST /v1/apps`** + **`POST /v1/deployments`** for the [erp_lab](https://github.com/souravs72/erp_lab) preset. See **[CLI.md](./CLI.md)** for flags.

---

## Configuration reference (`backend/.env`)

Copy from **`backend/.env.example`** and set at least:

| Variable | Purpose |
|----------|---------|
| **`DATABASE_URL`** | SQLAlchemy URL for PostgreSQL (e.g. `postgresql+psycopg://user:pass@db:5432/theiux`). |
| **`REDIS_URL`** | Redis for RQ (e.g. `redis://redis:6379/0` — match your Compose service name and port). |
| **`JWT_SECRET`** | Strong secret for signing access/refresh tokens. **Rotate in production.** |
| **`THEIUX_CLI_PATH`** | Absolute path **inside the worker container** to the `theiux` executable (e.g. `/theiux/bin/theiux`). |
| **`AWS_PROFILE`** | With **`~/.aws`** mounted in Compose, profile for Terraform (backend) and **`aws`** (worker). See **[SETUP.md](./SETUP.md)**. |
| **`AWS_ACCESS_KEY_ID`** / **`AWS_SECRET_ACCESS_KEY`** / **`AWS_SESSION_TOKEN`** | Alternative to profile; never commit real values. |
| **`THEIUX_DEPLOY_TIMEOUT_SECONDS`** | Wall-clock cap for a single `theiux deploy-site` run (default **3600**). |
| **`THEIUX_INIT_TIMEOUT_SECONDS`** | Wall-clock cap for **`POST /v1/admin/theiux-init`** (Terraform apply). |
| **`ALLOWED_RUNTIME_VERSIONS`** | Comma-separated `runtime:version` pairs users may select when creating an app. |
| **`BOOTSTRAP_ADMIN_EMAIL`** | Optional. With **`BOOTSTRAP_ADMIN_PASSWORD`**, creates a user **`role=admin`** once at API startup if that email does not exist. Password must be **≥ 12 characters**. Do not commit real secrets. |
| **`BOOTSTRAP_ADMIN_PASSWORD`** | Strong random value (e.g. `openssl rand -base64 24`). Change after first login (see below). |

Optional: **`AUTH_SECURE_COOKIES`**, **`AUTH_RATE_LIMIT_*`**, **`DEPLOY_RETRY_RATE_LIMIT_PER_MINUTE`**, **`QUEUE_MAX_DEPTH`**, **`CIRCUIT_WORKER_LAG_SECONDS`**, **`ENABLE_REFRESH_TOKEN_BINDING`**. See **`backend/docs/API_CONTRACT.md`** for behavior.

### Bootstrap admin and password changes

1. Set **`BOOTSTRAP_ADMIN_EMAIL`** and **`BOOTSTRAP_ADMIN_PASSWORD`** in **`backend/.env`** (both required together, or omit both).
2. Restart the **backend** container. On startup it runs **`seed_bootstrap_admin()`** after plans are seeded. If a user with that email already exists, **nothing** is changed (no password overwrite from env).
3. Sign in via the web UI with that email and password.
4. Rotate the password with the operator CLI — see **[CLI](CLI.md)** (`set-password`).

**Frontend** (`frontend/.env.local`):

| Variable | Purpose |
|----------|---------|
| **`NEXT_PUBLIC_API_BASE_URL`** | Base URL of the API **as seen by the browser** (e.g. `https://api.example.com`). No trailing slash. |

---

## Database migrations

The backend Docker image runs **`alembic upgrade head`** before **uvicorn** starts. For manual runs:

```bash
cd backend && alembic upgrade head
```

Use the same **`DATABASE_URL`** as production.

Latest migrations add SaaS entities for:

- organizations and organization_members
- subscriptions
- site_domains and site_backups

When upgrading from older versions, run migrations before rolling the web app to avoid missing-table API failures on team/billing/site ops screens.

---

## Worker process

The **worker** service runs **`python -m app.worker`**. It must:

- Share the same **`DATABASE_URL`** and **`REDIS_URL`** as the API.
- Have **`THEIUX_CLI_PATH`** pointing to a working **`theiux`** binary.
- Have **`theiux`** able to read **`bin/.theiux-context`** (from **`theiux init`**) and call AWS SSM.

If deploys never leave **queued** / **running**, check worker logs, Redis connectivity, and that the CLI runs interactively on the host with the same mount and env.

---

## Production hardening

Follow **[PRODUCTION_CHECKLIST.md](./PRODUCTION_CHECKLIST.md)** for health checks, backups, rate limits, HTTPS, and failure drills.

Additional operator notes:

- **Secrets**: Never commit **`.env`** files. Use a secret manager or sealed env in your orchestrator.
- **HTTPS**: Terminate TLS at your load balancer or ingress; set **`NEXT_PUBLIC_API_BASE_URL`** to the public API URL.
- **SSM / long deploys**: The `theiux` script polls SSM until the command finishes or a local time limit is hit. Tunables such as **`THEIUX_SSM_WAIT_MAX_SECONDS`** and **`THEIUX_SSM_POLL_SECONDS`** are documented in the **`theiux`** repository’s shell scripts (see comments in **`bin/theiux`**).
- **Observability**: Monitor **`GET /health`**, API 5xx rate, queue depth, and job **`dead_letter`** counts.

---

## Troubleshooting

| Symptom | Things to check |
|---------|-----------------|
| **Job log: `Run 'theiux init' first.`** | Create **`bin/.theiux-context`** via **`/admin/theiux-init`** or host **`./bin/theiux init`**; restart the worker. Confirm Compose **`../theiux`** mount. See **[SETUP.md](./SETUP.md)**. |
| **Terraform: `No valid credential sources`** | **`~/.aws`** mounted on **backend**, **`AWS_PROFILE`** (or keys) in **`backend/.env`**. |
| **Terraform: missing `aws_region` / `repo_url`** | Use the UI form or set **`TF_VAR_`** on the host. |
| **`terraform: command not found`** | Rebuild **backend** image; ensure the browser calls the Compose API (**port 8001**), not another process on **8000**. |
| **401 / login failures** | JWT secret, clock skew, cookie domain if using cookie auth. |
| **Deploy stuck** | Worker running? **`theiux`** path? AWS credentials **inside the worker container**? SSM agent on target instance? |
| **Immediate deploy failure** | Worker logs; `theiux deploy-site` stderr in job logs; **`THEIUX_DEPLOY_TIMEOUT_SECONDS`** too low? |
| **Frontend cannot reach API** | **`NEXT_PUBLIC_API_BASE_URL=http://localhost:8001`**, CORS, firewall, mixed HTTP/HTTPS. |
| **Port bind errors** | Change host ports in **`docker-compose.yml`** and **`NEXT_PUBLIC_API_BASE_URL`**. |

---

## Related documents

- **[SETUP.md](./SETUP.md)** — first-time install (env, AWS, ports, platform init).
- **[CLI](./CLI.md)** — `python -m app.cli` (password changes, `--help`).
- **[End-user deployment guide](./END_USER_DEPLOYMENT_GUIDE.md)** — for people who deploy *apps* through this product.
- **`backend/docs/API_CONTRACT.md`** — HTTP API details.
- **`docs/PRODUCTION_CHECKLIST.md`** — production readiness checklist.
