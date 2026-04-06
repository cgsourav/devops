# Theiux Control Plane — API contract (`/v1`)

All application endpoints are under the **`/v1`** prefix. A non-versioned **`GET /health`** exists for probes (same payload as **`GET /v1/health`**, omitted from OpenAPI).

Interactive docs: **`GET /docs`**, schema: **`GET /openapi.json`**.

## Error envelope

Non-2xx responses (except CSRF middleware, which uses the same shape) use:

```json
{
  "code": "string",
  "message": "string",
  "category": "string",
  "details": null
}
```

- **`code`**: stable identifier (`not_found`, `queue_full`, `circuit_open`, `validation_error`, …).
- **`category`**: coarse grouping (`client_error`, `auth_error`, `rate_limit`, `queue_full`, `circuit_open`, `migration_error`, …).
- **`details`**: optional object (`null`, validation errors array, `last_error_type` context, etc.).

`422` validation errors set `details` to the Pydantic/Starlette error list.

Rate-limited responses may include **`Retry-After`** (seconds).

HTTP status codes:

| Code | Meaning |
|------|---------|
| 400 | Bad request / invalid domain rules |
| 401 | Missing or invalid auth / refresh |
| 403 | CSRF failure (cookie mode) |
| 404 | Resource not found (or not owned) |
| 409 | Conflict (invalid state transition, retry not allowed) |
| 422 | Request body/query validation |
| 429 | Rate limit or queue full |
| 500 | Server error (including classified migration failures) |
| 503 | Circuit open (worker heartbeat / lag) |

## Auth & tokens

- **Access JWT** (`Authorization: Bearer …`): claims include `type=access`, `scope=access`.
- **Refresh JWT** (body or `refresh_token` cookie): claims include `type=refresh`, `scope=refresh`.
- **`token_use`** in `TokenOut` is always **`access`** (the credential used for API calls); the refresh value is returned separately.

Optional **`AUTH_SECURE_COOKIES=true`**: sets `access_token`, `refresh_token`, and `csrf_token` cookies. **CSRF**: mutating requests that rely on cookies without `Authorization: Bearer` must send **`X-CSRF-Token`** matching the **`csrf_token`** cookie (double-submit).

Optional **`ENABLE_REFRESH_TOKEN_BINDING=true`**: stores a SHA-256 of `User-Agent` on refresh token rows; refresh must match.

---

## Endpoints

### Auth (`tags: auth`)

| Method | Path | Request | Response | Status |
|--------|------|---------|----------|--------|
| POST | `/v1/auth/register` | `RegisterIn` | `RegisterOut` | 201/200, 409 |
| POST | `/v1/auth/login` | OAuth2 form (`username`, `password`) | `TokenOut` | 200, 401 |
| POST | `/v1/auth/refresh` | `RefreshIn` body optional | `TokenOut` | 200, 401 |
| POST | `/v1/auth/logout` | `LogoutIn` body optional | `LogoutOut` | 200 |
| GET | `/v1/me` | — | `UserMeOut` (`id`, `email`, `role`, `default_org_id`) | 200, 401 |

### Admin (`tags: admin`)

| Method | Path | Request | Response | Status |
|--------|------|---------|----------|--------|
| POST | `/v1/admin/theiux-init` | `TheiuxInitIn` (`aws_region`, `repo_url`, optional `repo_ref`, `project_name`, `environment`, `instance_type`, `root_volume_size_gb`) | `TheiuxInitOut` (`ok`, `exit_code`, `stdout`, `stderr`) | 200, 401, 403, 422 |

Runs `theiux init` on the API host; variables are passed as `TF_VAR_*` to Terraform (see `theiux/terraform/variables.tf`). Requires **`require_min_role('admin')`**: roles **`admin`** or **`owner`** (same as `POST /v1/deployments`); **`viewer`** is denied. The API container must include Terraform, AWS CLI, and credentials.

### Plans (`tags: plans`)

| Method | Path | Request | Response | Status |
|--------|------|---------|----------|--------|
| GET | `/v1/plans` | — | `PlanOut[]` | 200, 401 |

### Team / Tenancy (`tags: team`)

| Method | Path | Request | Response | Status |
|--------|------|---------|----------|--------|
| GET | `/v1/team` | — | `TeamOut` (`organization_id`, `organization_name`, `members[]`) | 200, 401 |
| POST | `/v1/team/invite` | `TeamInviteIn` (`email`, `role`) | `TeamInviteOut` | 200, 401, 403 |

### Billing (`tags: billing`)

| Method | Path | Request | Response | Status |
|--------|------|---------|----------|--------|
| GET | `/v1/billing/subscription` | — | `SubscriptionOut` | 200, 401 |
| POST | `/v1/billing/subscription/select-plan` | `SubscriptionSelectPlanIn` | `SubscriptionSelectPlanOut` | 200, 401, 403, 404 |

### Apps (`tags: apps`)

Bench-scoped **source apps** (git definitions). `AppOut.app_id` in deployments is the **`bench_source_apps.id`** (same id returned here).

| Method | Path | Request | Response | Status |
|--------|------|---------|----------|--------|
| GET | `/v1/app-presets` | — | `AppPresetOut[]` (from **`app_presets`** table when migrated + seeded; else static fallback) | 200, 401 |
| POST | `/v1/apps` | `AppCreateIn` (optional `bench_id`; default bench per user) | `AppOut` | 200, 400, 401 |
| GET | `/v1/apps` | — | `AppOut[]` | 200, 401 |

### Benches (`tags: benches`)

| Method | Path | Request | Response | Status |
|--------|------|---------|----------|--------|
| GET | `/v1/benches` | — | `BenchOut[]` | 200, 401 |
| POST | `/v1/benches` | `BenchCreateIn` | `BenchOut` | 200, 401, 422 |
| GET | `/v1/benches/{bench_id}` | — | `BenchOut` | 200, 401, 404 |
| POST | `/v1/benches/{bench_id}/sync` | — | `{ ok, bench_id, message }` | 200, 401, 404, 429, 503 |
| GET | `/v1/benches/{bench_id}/source-apps` | — | `BenchSourceAppOut[]` | 200, 401, 404 |
| POST | `/v1/benches/{bench_id}/source-apps` | `BenchSourceAppCreateIn` | `BenchSourceAppOut` | 200, 401, 404, 422 |
| GET | `/v1/benches/{bench_id}/sites` | — | `SiteOut[]` | 200, 401, 404 |
| GET | `/v1/benches/{bench_id}/deployments` | — | `DeploymentOut[]` | 200, 401, 404 |
| POST | `/v1/benches/{bench_id}/fetch-app/{bsa_id}` | — | `DeploymentOut` (`operation=get_app_bench`) | 200, 401, 404, 429, 503 |

### Deployments (`tags: deployments`)

| Method | Path | Request | Response | Status |
|--------|------|---------|----------|--------|
| POST | `/v1/deployments` | `DeploymentCreateIn` (`app_id` = bench source app id) | `DeploymentOut` (`operation` default `full_site`) | 200, 400, 401, 404, 429, 503 |
| GET | `/v1/deployments` | — | `DeploymentOut[]` | 200, 401 |
| POST | `/v1/deployments/{deployment_id}/retry` | — | `DeploymentRetryOut` | 200, 401, 404, 409, 429, 503 |
| POST | `/v1/deployments/{deployment_id}/transition/{next_state}` | — | `DeploymentTransitionOut` | 200, 401, 404, 409 |

### Logs (`tags: logs`)

| Method | Path | Query | Response | Status |
|--------|------|-------|----------|--------|
| GET | `/v1/deployments/{deployment_id}/logs` | — | `DeploymentLogsPlainOut` | 200, 401, 404 |
| GET | `/v1/deployments/{deployment_id}/logs/structured` | `offset` (≥0), `limit` (1–500), `errors_only` | `DeploymentLogsStructuredOut` | 200, 401, 404 |

**`last_error_type`** (when present on deployment/job failures): `build_error` | `migration_error` | `runtime_error` (heuristic).

### Sites (`tags: sites`)

| Method | Path | Request | Response | Status |
|--------|------|---------|----------|--------|
| GET | `/v1/sites` | — | `SiteOut[]` (`bench_id`, no legacy `app_id`) | 200, 401 |
| GET | `/v1/sites/{site_id}` | — | `SiteDetailOut` (`site`, nested `apps`) | 200, 401, 404 |
| GET | `/v1/sites/{site_id}/apps` | — | `SiteAppOut[]` | 200, 401, 404 |
| POST | `/v1/sites/{site_id}/sync` | — | `{ ok, bench_id, message }` (queues bench inventory job) | 200, 401, 404, 429, 503 |
| POST | `/v1/sites/{site_id}/install-app/{bsa_id}` | — | `DeploymentOut` (`operation=install_app`) | 200, 401, 404, 429, 503 |
| POST | `/v1/sites/{site_id}/uninstall-app/{bsa_id}` | — | `DeploymentOut` (`operation=uninstall_app`) | 200, 401, 404, 429, 503 |
| POST | `/v1/sites/{site_id}/migrate` | — | `MigrateSuccessOut` | 200, 404, 500 |
| GET | `/v1/sites/{site_id}/domains` | — | `SiteDomainOut[]` | 200, 401, 404 |
| POST | `/v1/sites/{site_id}/domains` | `SiteDomainIn` | `SiteDomainOut` | 200, 401, 403, 404 |
| POST | `/v1/sites/{site_id}/domains/{domain_id}/verify` | — | `SiteDomainOut` | 200, 401, 403, 404 |
| GET | `/v1/sites/{site_id}/backups` | — | `SiteBackupOut[]` | 200, 401, 404 |
| POST | `/v1/sites/{site_id}/backups` | — | `SiteBackupCreateOut` | 200, 401, 403, 404 |
| POST | `/v1/sites/{site_id}/restore` | `SiteRestoreIn` (`backup_id`) | `SiteRestoreOut` | 200, 401, 403, 404 |
| DELETE | `/v1/sites/{site_id}` | — | 204 | 204, 401, 404 |

On migration failure, body is the **error envelope** with `code=migration_failed` and `category` from classification.

### System (`tags: system`)

| Method | Path | Response | Status |
|--------|------|----------|--------|
| GET | `/v1/health` | `HealthOut` | 200 |

---

## Examples

### Deploy request (`DeploymentCreateIn`)

```json
{ "app_id": "550e8400-e29b-41d4-a716-446655440000" }
```

### Structured logs (`DeploymentLogsStructuredOut`)

```json
{
  "status": "building",
  "total": 2,
  "offset": 0,
  "limit": 100,
  "entries": [
    { "ts": "2026-03-25T12:00:00+00:00", "level": "info", "message": "[theiux] building" },
    { "ts": "2026-03-25T12:00:01+00:00", "level": "error", "message": "ERROR [build_error]: ..." }
  ]
}
```

### Migrate — success

```json
{ "ok": true }
```

### Migrate — failure (envelope)

```json
{
  "code": "migration_failed",
  "message": "relation does not exist",
  "category": "migration_error",
  "details": { "site_id": "…" }
}
```

---

## Safeguards (config)

| Setting | Purpose |
|---------|---------|
| `DEPLOY_RETRY_RATE_LIMIT_PER_MINUTE` | Per-user limit for `POST /deployments` and `POST .../retry` (default `3`) |
| `QUEUE_MAX_DEPTH` | Max RQ queue length before `429` (`0` = disabled) |
| `CIRCUIT_WORKER_LAG_SECONDS` | If worker heartbeat age &gt; this, `503` (`0` = disabled) |

Worker process sets Redis key `cp:worker:heartbeat` (see `worker.py`).
