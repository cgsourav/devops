# Theiux DevOps Monorepo

Production-focused platform for hosting and operating Frappe workloads with a dedicated control plane.

This repository contains two connected projects:

- `theiux`: AWS deployment/runtime stack for multi-tenant Frappe hosting.
- `theiux-control-plane`: Web control plane (Next.js + FastAPI) for orchestration, deployment operations, and platform administration.

## Repository Structure

```text
devops/
├── theiux/                 # Runtime/deployment stack (Docker, scripts, CI, IaC)
└── theiux-control-plane/   # Control plane app (frontend + backend + worker)
```

## What This Platform Provides

- Multi-tenant Frappe runtime with shared worker model.
- Automated deploy workflows with health checks and rollback safeguards.
- Container image delivery via GHCR and deployment automation via AWS SSM.
- HTTPS/TLS automation, routing support, and operational scripts for site lifecycle.
- Operator and tenant-facing control plane for managing deployments and platform state.

## Quick Start Paths

### 1) Run the Frappe runtime stack (`theiux`)

```bash
cd theiux
cp .env.example .env
# update required values in .env
docker compose -f docker-compose.yml -f docker-compose.local.yml \
  --profile internal-db --profile internal-redis up -d
```

Use this path when you want to run or validate the hosting/runtime layer.

### 2) Run the control plane (`theiux-control-plane`)

```bash
cd theiux-control-plane
docker compose up --build
```

- UI: `http://localhost:3001`
- API: `http://localhost:8001`

Use this path when you want to operate deployments through the web/API control plane.

## Recommended Workflow

1. Build and validate infrastructure/runtime behavior in `theiux`.
2. Use `theiux-control-plane` to manage app/deployment operations.
3. Keep environment contracts aligned across both projects (`.env.example` files).
4. Prefer immutable commit SHA image tags for deterministic deploys.

## Documentation Map

- Runtime stack docs: `theiux/README.md`
- Control plane docs: `theiux-control-plane/README.md`
- Control plane setup guide: `theiux-control-plane/docs/SETUP.md`
- Operator guide: `theiux-control-plane/docs/OPERATOR_GUIDE.md`

## Deployment Notes

- Mainline deployment automation is centered on `main`.
- GHCR is used for container publishing and pull-based deploys.
- AWS SSM parameters provide environment/config injection during deploy.
- Local development uses `docker-compose.local.yml` overrides to avoid cloud-only logging dependencies.

---

If you are new to the repo, start with the subproject README for the area you are changing first, then return here for cross-project context.
