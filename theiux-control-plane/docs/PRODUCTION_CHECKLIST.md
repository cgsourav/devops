# Minimal production checklist

Complete **before** onboarding more than a handful of users.

## Health & uptime

- [ ] **`GET /health`** (or **`GET /v1/health`**) is wired into your uptime / synthetic checks (status **200**, JSON `status: ok`).
- [ ] Load balancer or ingress health probes use the same path and do not require auth.

## Observability (AWS example: CloudWatch)

- [ ] **API 5xx rate**: alarm on `5xx` responses from the API target group or application (threshold and window per your SLO).
- [ ] **Job failure rate**: metric from worker logs or DB (`jobs` / `dead_letter` counts) with alarm when failure ratio or count exceeds baseline.
- [ ] **Queue lag**: Redis `deployments` queue depth or age of oldest job; alarm when lag exceeds a few minutes (tune to your deploy cadence).

## Data

- [ ] **Backups**: Postgres (and Redis if you persist anything critical) on a schedule; **restore drill** documented and run (UI or runbook), not only “backup exists.”

## Security & abuse

- [ ] **Rate limits** verified under load: **auth** (`AUTH_RATE_LIMIT_*`) and **deploy/retry** (`DEPLOY_RETRY_RATE_LIMIT_PER_MINUTE`).
- [ ] **JWT / secrets** rotated from dev defaults; **HTTPS** only in production.

## Failure drill

- [ ] **One intentional failure**: e.g. invalid repo URL or bad dependency **in a non-prod** environment; confirm UI shows **`last_error_type`**, structured logs, retry returns a **new deployment id**, and audit trail entries look correct.

## Notes

- CloudWatch alarms are **examples**; use Datadog, Grafana, New Relic, etc. with equivalent signals.
- For **queue lag**, RQ exposes queue length; worker heartbeat is `cp:worker:heartbeat` in Redis when using the bundled worker.
