# Control plane CLI

Short reference for operator commands shipped with the **backend** (`app/cli.py`).

## How to run

From the **control plane repo root** (with Compose):

```bash
docker compose exec backend python -m app.cli --help
```

Locally (needs **`backend/.env`** and DB reachable):

```bash
cd backend && PYTHONPATH=. python -m app.cli --help
```

---

## Commands

### `set-password`

Update a user’s password by email (min **8** characters).

**Interactive** (password not echoed; best default):

```bash
docker compose exec backend python -m app.cli set-password --email you@example.com
```

**Non-interactive** (avoid on shared shells—history may record the flag):

```bash
docker compose exec backend python -m app.cli set-password --email you@example.com --password 'your-new-password'
```

### `enqueue-curated-app`

Create the **erp_lab** (or another [curated preset](../backend/app/curated_presets.py)) **App** row for an existing user and enqueue the **same** deployment job as **`POST /v1/deployments`**. Use when you want to bootstrap a tenant without clicking through the UI.

Requirements: user must exist and have **`admin`** or **`owner`** role (same as the API). **`ALLOWED_RUNTIME_VERSIONS`** must include the preset’s runtime (e.g. **`python:3.11`**).

```bash
docker compose exec backend python -m app.cli enqueue-curated-app --preset erp_lab --email user@example.com
```

Optional: **`--plan-name Free`** (otherwise the **lowest-priced** plan is used). **`--app-only`** creates only the **App** row and does not enqueue a deploy.

---

## Related

- **Bootstrap admin** on first deploy: env **`BOOTSTRAP_ADMIN_EMAIL`** / **`BOOTSTRAP_ADMIN_PASSWORD`** — see **[Operator guide](OPERATOR_GUIDE.md)**.
- **DB migrations:** `alembic upgrade head` (see Operator guide).
