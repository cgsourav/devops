# First-time setup (control plane)

This guide walks through **everything** needed to run the Theiux control plane locally or on a single host with Docker Compose: repository layout, environment files, AWS credentials for Terraform and deployments, ports, and optional platform init from the UI.

**Who this is for:** operators setting up the stack for the first time. For day‑to‑day operations after install, see **[Operator guide](./OPERATOR_GUIDE.md)**.

---

## 1. Prerequisites

| Requirement | Notes |
|---------------|--------|
| **Docker** and **Docker Compose** | Recent stable versions (Compose v2). |
| **AWS account** | Permissions to create EC2, VPC, IAM, SSM, ECR, etc. (as defined in `theiux/terraform`). |
| **AWS CLI on your host** (recommended) | `aws configure` or SSO so `~/.aws` exists; verify with `aws sts get-caller-identity`. |
| **Two repositories** | This repo (`theiux-control-plane`) and the **`theiux`** automation repo (scripts + `bin/theiux` + Terraform). |

You do **not** need Terraform or the AWS CLI installed on the host **if** you only use Docker Compose: the **backend** image includes Terraform and AWS CLI. You **do** need AWS credentials visible **inside** the backend and worker containers (see below).

---

## 2. Directory layout

Compose expects the **`theiux`** repo next to this repo by default:

```text
devops/
  theiux-control-plane/     ← this repository (clone here)
  theiux/                   ← theiux automation repo (clone sibling)
```

The compose file mounts **`../theiux` → `/theiux`** on the backend and worker. If your checkout lives elsewhere, edit **`docker-compose.yml`** and change both `../theiux` paths, and set **`THEIUX_CLI_PATH=/theiux/bin/theiux`** in **`backend/.env`** (path inside the container).

---

## 3. Environment files

From **`theiux-control-plane`** root:

```bash
cp backend/.env.example backend/.env
cp frontend/.env.example frontend/.env.local
```

### Backend (`backend/.env`)

| Variable | What to set |
|----------|-------------|
| **`JWT_SECRET`** | Long random string (e.g. `openssl rand -hex 32`). **Do not use the example value in production.** |
| **`DATABASE_URL`** | Default `postgresql+psycopg://theiux:theiux@db:5432/theiux` matches Compose Postgres. |
| **`REDIS_URL`** | Default `redis://redis:6379/0` matches Compose Redis. |
| **`THEIUX_CLI_PATH`** | Usually `/theiux/bin/theiux` (path **inside** the container). |
| **`AWS_PROFILE`** | After you mount `~/.aws` (step 5), set e.g. `default` or your profile name. **Or** use access keys (see `.env.example`). |

Leave other variables as in the example until you need to tune them.

### Frontend (`frontend/.env.local`)

| Variable | What to set |
|----------|-------------|
| **`NEXT_PUBLIC_API_BASE_URL`** | Base URL of the API **as the browser opens it**. With default Compose this must be **`http://localhost:8001`** (backend is published on host port **8001**). No trailing slash. |

If this URL is wrong, the UI will call a different process (for example something on port 8000) and Terraform or auth will fail in confusing ways.

---

## 4. Ports (default Compose)

| Service | Host port | Container | Purpose |
|---------|-----------|-----------|---------|
| **Frontend** | **3001** | 3000 | Next.js UI — open **`http://localhost:3001`** |
| **Backend API** | **8001** | 8000 | Must match **`NEXT_PUBLIC_API_BASE_URL`** |
| **PostgreSQL** | 5434 | 5432 | Optional host access for debugging |
| **Redis** | 6381 | 6379 | Optional host access |

Port **8001** is used for the API so it does not conflict with another app on **8000** on your machine.

---

## 5. AWS credentials inside Docker

Terraform runs **inside the backend** container. The worker runs **`aws ssm`** via **`theiux`**. Both need **valid AWS credentials** in their environment.

### Option A — Mount host `~/.aws` (default in Compose)

**`docker-compose.yml`** already mounts **`~/.aws:/root/.aws:ro`** on **backend** and **worker**. Ensure:

1. **`~/.aws`** exists on the host and `aws sts get-caller-identity` works.
2. **`backend/.env`** sets **`AWS_PROFILE`** (e.g. **`default`**) to match your local profile name.
3. If **`~/.aws` does not exist** yet, either run **`aws configure`** first or **remove** the two **`~/.aws`** volume lines from **`docker-compose.yml`** and use Option B instead.

Restart after changes: **`docker compose up --build`**.

### Option B — Environment variables in `backend/.env`

Do **not** commit secrets. Set **`AWS_ACCESS_KEY_ID`**, **`AWS_SECRET_ACCESS_KEY`**, and **`AWS_DEFAULT_REGION`** (and **`AWS_SESSION_TOKEN`** if you use temporary credentials). **Remove** the **`~/.aws`** volume lines from **`docker-compose.yml`** if you rely only on keys (optional; mounting an empty dir is harmless only if keys are set).

### Why this matters

If credentials are missing, Terraform fails with:

- **No valid credential sources found** / **no EC2 IMDS role**

The API container is not an EC2 instance with an instance role unless you attach one in your orchestrator—so **profile or keys** are required.

---

## 6. Start the stack

```bash
cd /path/to/theiux-control-plane
docker compose up --build
```

- **UI:** `http://localhost:3001`
- **API docs:** `http://localhost:8001/docs`
- **Health:** `http://localhost:8001/v1/health`

If the frontend fails with a **lockfile** or **permission** error, the Compose file already uses an anonymous volume for **`/app/.next`** so Next.js can write caches; recreate containers if you changed volumes.

---

## 7. Platform init (Terraform) — two ways

You need **`bin/.theiux-context`** under the mounted **`theiux`** repo before deploys work. **Region** and **Git repo URL** are required Terraform inputs (`aws_region`, `repo_url` in `theiux/terraform/variables.tf`).

### A. From the UI (recommended for operators)

1. Register or sign in. The first user is often **`owner`** (see **[Operator guide](./OPERATOR_GUIDE.md)** for restricting who can register).
2. Open **`/admin/theiux-init`** (link from the dashboard when available).
3. Fill in **AWS region** and **Git repository URL** (HTTPS, SSH, or `git@…`). Optionally expand **optional Terraform fields** (branch, instance type, etc.).
4. **Run theiux init**. The API passes variables as **`TF_VAR_*`** to Terraform and runs **`theiux init`** in the mounted repo.

Requirements:

- **AWS credentials** in the **backend** container (step 5).
- **Backend** mount of **`theiux`** is **read-write** (default in Compose) so **`bin/.theiux-context`** can be written.

### B. From the host CLI

```bash
cd /path/to/theiux
export TF_VAR_aws_region=ap-south-1
export TF_VAR_repo_url=https://github.com/org/repo.git
./bin/theiux init
```

Then restart Compose so the worker sees the file at **`/theiux/bin/.theiux-context`**.

---

## 8. Database migrations

After pulling new backend code, apply the schema from the **`theiux-control-plane/backend`** directory (for example inside the **backend** container):

```bash
alembic upgrade head
```

This includes **benches**, **bench source apps**, **site apps**, and the **`app_presets`** catalog (seeded on API startup from the curated registry).

---

## 9. UI navigation (benches, sites, deploy)

- **Sign in** at **`/`** (session stored in the browser).
- **`/benches`** — list and create logical benches; open a bench for **Sites**, **Source apps**, and **Deployments**.
- **`/sites/<siteId>`** — site **Overview** (quotas and plan names from the bench catalog) and **Apps** (install / uninstall / inventory refresh).
- **`/deploy`** — deploy wizard and deployment logs. Use **`/deploy?deployment=<deployment_uuid>`** to open the log view for a specific deployment (for example from a bench’s deployment list).

---

## 10. Worker and deploys

The **worker** uses **`theiux deploy-site`** and **AWS SSM**. It must:

- Read **`/theiux/bin/.theiux-context`** (same mount as the host file).
- Have **AWS credentials** (mount **`~/.aws`** and **`AWS_PROFILE`**, or the same keys as in **`backend/.env`** via shared **`env_file`**).

If jobs say **`Run 'theiux init' first`**, create the context file (UI or CLI) and restart the worker if needed.

---

## 11. Optional: bootstrap admin

In **`backend/.env`**, set both **`BOOTSTRAP_ADMIN_EMAIL`** and **`BOOTSTRAP_ADMIN_PASSWORD`** (password ≥ 12 characters). Restart the backend once. A user with that email is created if it does not exist. Rotate the password with **[CLI](./CLI.md)** (`set-password`).

---

## 12. Quick troubleshooting

| Problem | What to check |
|---------|----------------|
| **`terraform: command not found`** | Rebuild the backend image: **`docker compose build --no-cache backend`**. Ensure the browser hits the **Compose** API on **8001**, not another process on **8000**. |
| **`No valid credential sources found` (Terraform)** | Mount **`~/.aws`** for **backend** and set **`AWS_PROFILE`** (or use keys in **`backend/.env`**). Restart Compose. |
| **`No value for required variable`** (Terraform) | Use the UI **platform init** form and set **region** and **repo URL**, or export **`TF_VAR_aws_region`** and **`TF_VAR_repo_url`** on the host before **`./bin/theiux init`**. |
| **Frontend cannot reach API** | **`NEXT_PUBLIC_API_BASE_URL=http://localhost:8001`** in **`frontend/.env.local`**; rebuild the frontend container if env was baked at build time. |
| **`Run 'theiux init' first`** in job logs | **`.theiux-context`** missing or wrong mount path; run **`theiux init`** (UI or host) and restart worker. |
| **Port already in use** | Change the host port in **`docker-compose.yml`** and update **`NEXT_PUBLIC_API_BASE_URL`** to match. |

---

## Next steps

- **[Operator guide](./OPERATOR_GUIDE.md)** — configuration reference, production tuning, troubleshooting.
- **[CLI](./CLI.md)** — `python -m app.cli` (password changes).
- **[API contract](../backend/docs/API_CONTRACT.md)** — HTTP API details.
