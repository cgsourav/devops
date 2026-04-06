# Theiux Control Plane

Production-grade control plane with:

- Next.js frontend
- FastAPI backend
- PostgreSQL + Alembic migrations
- Redis + RQ worker queue
- Safe `theiux` CLI integration (real deploys via AWS SSM)

## First-time setup

**Start here:** **[docs/SETUP.md](docs/SETUP.md)** — step-by-step instructions for directory layout, `backend/.env` and `frontend/.env.local`, Docker Compose ports (**8001** API, **3001** UI), mounting **`~/.aws`** for Terraform and the worker, and running **platform init** (UI or CLI) so **`bin/.theiux-context`** exists.

Quick start after configuration:

```bash
cd theiux-control-plane
docker compose up --build
```

- UI: `http://localhost:3001`
- API: `http://localhost:8001` (OpenAPI at `/docs`)

## Documentation

| Doc | Audience |
|-----|----------|
| **[SETUP.md](docs/SETUP.md)** | **Anyone** installing the stack for the first time |
| **[Operator guide](docs/OPERATOR_GUIDE.md)** | Ongoing operations, config reference, production |
| **[CLI](docs/CLI.md)** | `python -m app.cli` (e.g. `set-password`) |
| **[End-user deployment guide](docs/END_USER_DEPLOYMENT_GUIDE.md)** | People who deploy *apps* through this product |
| **[API contract](backend/docs/API_CONTRACT.md)** | HTTP API details |

## Capabilities

- Register/login
- Create apps from Git repository
- Select runtime versions and pricing plan
- Create deployment record → enqueue job → process through theiux integration
- Real-time log polling via API
- Clean error reporting in UI
- Site listing and migration action endpoint
- Admin: platform Terraform init (`/admin/theiux-init`) for operators with **admin** / **owner** role

## Stitch MCP output

UI design artifacts generated through Stitch MCP are tracked in `frontend/stitch-artifacts.json`.
