"""Queue, worker, and RQ visibility (no new frameworks)."""

import time
from typing import Any

from rq.registry import StartedJobRegistry

from app.metrics import snapshot as metrics_snapshot
from app.queue import queue, redis_conn


def _heartbeat_ts() -> float | None:
    raw = redis_conn.get('cp:worker:heartbeat')
    if raw is None:
        return None
    try:
        s = raw.decode() if isinstance(raw, (bytes, bytearray)) else str(raw)
        return float(s)
    except (ValueError, TypeError):
        return None


def worker_status_payload() -> dict[str, Any]:
    """Shared fields for /workers/status and /metrics."""
    now = time.time()
    try:
        hb = _heartbeat_ts()
        age = None if hb is None else round(now - hb, 2)
        qdepth = len(queue)
        try:
            started = StartedJobRegistry(queue=queue)
            started_count = started.count
        except Exception:
            started_count = None
        return {
            'last_heartbeat_unix': hb,
            'heartbeat_age_seconds': age,
            'queue_depth': qdepth,
            'started_jobs': started_count,
        }
    except Exception:
        # Redis unreachable or RQ misconfigured — still return 200 with degraded fields.
        return {
            'last_heartbeat_unix': None,
            'heartbeat_age_seconds': None,
            'queue_depth': 0,
            'started_jobs': None,
        }


def metrics_export_payload() -> dict[str, Any]:
    base = metrics_snapshot()
    ws = worker_status_payload()
    return {
        **base,
        'queue_depth': ws['queue_depth'],
        'worker_last_heartbeat_unix': ws['last_heartbeat_unix'],
        'worker_heartbeat_age_seconds': ws['heartbeat_age_seconds'],
        'started_jobs': ws['started_jobs'],
    }
