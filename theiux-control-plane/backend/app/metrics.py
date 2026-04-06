from collections import defaultdict
from threading import Lock

_lock = Lock()
_metrics = {
    'requests_total': 0,
    'jobs_total': 0,
    'jobs_success': 0,
    'jobs_failed': 0,
    'job_duration_ms_sum': 0,
    'job_duration_ms_count': 0,
    'error_categories': defaultdict(int),
}

def record_request() -> None:
    with _lock:
        _metrics['requests_total'] += 1

def record_job(duration_ms: int, success: bool, category: str | None = None) -> None:
    with _lock:
        _metrics['jobs_total'] += 1
        if success:
            _metrics['jobs_success'] += 1
        else:
            _metrics['jobs_failed'] += 1
        _metrics['job_duration_ms_sum'] += max(duration_ms, 0)
        _metrics['job_duration_ms_count'] += 1
        if category:
            _metrics['error_categories'][category] += 1

def snapshot() -> dict:
    with _lock:
        duration_count = _metrics['job_duration_ms_count']
        avg_ms = (_metrics['job_duration_ms_sum'] / duration_count) if duration_count else 0
        return {
            'requests_total': _metrics['requests_total'],
            'jobs_total': _metrics['jobs_total'],
            'jobs_success': _metrics['jobs_success'],
            'jobs_failed': _metrics['jobs_failed'],
            'avg_job_duration_ms': round(avg_ms, 2),
            'error_categories': dict(_metrics['error_categories']),
        }
