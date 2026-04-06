"""Enqueue a new deployment job (shared by API and operator CLI)."""

from __future__ import annotations

import time
from collections import defaultdict, deque
from datetime import datetime, timezone

from rq import Retry
from sqlalchemy.orm import Session

from app.audit_service import write_audit
from app.config import settings
from app.errors import raise_api_error
from app.jobs import process_deployment
from app.models import BenchSourceApp, Deployment, Job, User
from app.queue import queue, redis_conn
from app.quotas import enforce_deploy_and_job_quotas

_deployment_user_limits: defaultdict[str, deque[float]] = defaultdict(deque)


def _worker_heartbeat_ts() -> float | None:
    raw = redis_conn.get('cp:worker:heartbeat')
    if raw is None:
        return None
    try:
        s = raw.decode() if isinstance(raw, (bytes, bytearray)) else str(raw)
        return float(s)
    except (ValueError, TypeError):
        return None


def check_queue_and_circuit() -> None:
    if settings.queue_max_depth and len(queue) >= settings.queue_max_depth:
        raise_api_error(
            status_code=429,
            code='queue_full',
            message='deployment queue is at capacity',
            category='queue_full',
            details={'queue_depth': len(queue), 'max_depth': settings.queue_max_depth},
            headers={'Retry-After': '60'},
        )
    if settings.circuit_worker_lag_seconds <= 0:
        return
    ts = _worker_heartbeat_ts()
    now = time.time()
    if ts is None:
        raise_api_error(
            status_code=503,
            code='circuit_open',
            message='worker heartbeat missing; temporarily unavailable',
            category='circuit_open',
            details={'heartbeat_age_seconds': None},
        )
    lag = now - ts
    if lag > settings.circuit_worker_lag_seconds:
        raise_api_error(
            status_code=503,
            code='circuit_open',
            message='worker lag exceeded; temporarily unavailable',
            category='circuit_open',
            details={'heartbeat_age_seconds': round(lag, 2), 'threshold_seconds': settings.circuit_worker_lag_seconds},
        )


def enforce_deploy_retry_rate_limit(user_id: str) -> None:
    now = time.time()
    window = _deployment_user_limits[user_id]
    while window and now - window[0] > 60:
        window.popleft()
    if len(window) >= settings.deploy_retry_rate_limit_per_minute:
        raise_api_error(
            status_code=429,
            code='deploy_rate_limited',
            message='too many deployment or retry requests',
            category='rate_limit',
            details={'limit_per_minute': settings.deploy_retry_rate_limit_per_minute},
            headers={'Retry-After': '60'},
        )
    window.append(now)


def enqueue_new_deployment(
    db: Session,
    user: User,
    bsa: BenchSourceApp,
    *,
    operation: str = 'full_site',
    context: dict | None = None,
) -> Deployment:
    """
    Create Deployment + Job and push to RQ. Caller must have verified bench ownership for bsa.
    """
    enforce_deploy_retry_rate_limit(user.id)
    check_queue_and_circuit()
    enforce_deploy_and_job_quotas(db, user.id)
    queued_at = datetime.now(timezone.utc).isoformat()
    dep = Deployment(
        bench_source_app_id=bsa.id,
        operation=operation,
        context=dict(context or {}),
        status='queued',
        stage_timestamps={'queued': queued_at},
    )
    db.add(dep)
    db.commit()
    db.refresh(dep)
    job = Job(
        deployment_id=dep.id,
        type='deploy',
        status='queued',
        logs='',
        logs_json=[],
        idempotency_key=f'deploy:{dep.id}',
        max_retries=3,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    queue.enqueue(process_deployment, job.id, retry=Retry(max=3, interval=[10, 30, 90]))
    write_audit(
        db,
        user_id=user.id,
        action='deploy',
        resource_type='deployment',
        resource_id=dep.id,
        metadata={'bench_source_app_id': bsa.id, 'operation': operation},
    )
    db.commit()
    return dep


def enqueue_bench_sync(bench_id: str) -> None:
    from app.jobs import process_bench_sync

    queue.enqueue(process_bench_sync, bench_id)
