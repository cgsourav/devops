import time
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import Bench, BenchSourceApp, Deployment, Job, Site, SiteApp
from app.metrics import record_job
from app.quotas import can_add_site
from app.theiux_cli import (
    TheiuxDeployError,
    apps_csv_for_bench,
    deploy_domain_for_app,
    stream_theiux_deploy,
    stream_theiux_get_app_only,
    stream_theiux_install_app_on_site,
    stream_theiux_inventory_bench,
    stream_theiux_inventory_site,
    stream_theiux_uninstall_app_from_site,
)

DEPLOYMENT_TRANSITIONS = {
    'queued': {'building'},
    'building': {'deploying', 'failed'},
    'deploying': {'success', 'failed'},
    'failed': {'rollback', 'deploying'},
    'rollback': {'stable'},
}


def _deployment_error_text(exc: Exception) -> str:
    if isinstance(exc, TheiuxDeployError):
        if exc.combined_output.strip():
            return f'{exc!s}\n\n--- captured output ---\n{exc.combined_output}'
        return str(exc)
    return str(exc)


def classify_error(exc: Exception) -> str:
    if isinstance(exc, TheiuxDeployError):
        return exc.category
    msg = str(exc).lower()
    if 'build' in msg:
        return 'build_error'
    if 'migrat' in msg:
        return 'migration_error'
    return 'runtime_error'


def _append(job: Job, line: str, level: str = 'info'):
    job.logs = (job.logs or '') + line + '\n'
    records = list(job.logs_json or [])
    records.append({'ts': datetime.now(timezone.utc).isoformat(), 'level': level, 'message': line})
    job.logs_json = records


def _transition_deployment(dep: Deployment, next_state: str):
    allowed = DEPLOYMENT_TRANSITIONS.get(dep.status, set())
    if next_state not in allowed:
        raise ValueError(f'invalid deployment transition {dep.status} -> {next_state}')
    dep.status = next_state


def _stamp_stage(dep: Deployment, key: str) -> None:
    m = dict(dep.stage_timestamps or {})
    m[key] = datetime.now(timezone.utc).isoformat()
    dep.stage_timestamps = m


def _transition_job(job: Job, next_state: str):
    allowed = {
        'queued': {'running'},
        'running': {'succeeded', 'failed'},
        'failed': {'retrying', 'dead_letter'},
        'retrying': {'running', 'failed'},
    }.get(job.status, set())
    if next_state not in allowed:
        raise ValueError(f'invalid job transition {job.status} -> {next_state}')
    job.status = next_state


def _ensure_site_app_link(db: Session, site: Site, bsa_id: str, state: str = 'installed') -> None:
    row = db.scalar(select(SiteApp).where(SiteApp.site_id == site.id, SiteApp.bench_source_app_id == bsa_id))
    if row:
        row.state = state
    else:
        db.add(SiteApp(site_id=site.id, bench_source_app_id=bsa_id, state=state))


def process_deployment(job_id: str):
    db: Session = SessionLocal()
    start = time.monotonic()
    try:
        job = db.get(Job, job_id)
        if not job:
            return
        if job.status in {'succeeded', 'dead_letter'}:
            return
        dep = db.get(Deployment, job.deployment_id)
        bsa = db.get(BenchSourceApp, dep.bench_source_app_id) if dep else None
        bench = db.get(Bench, bsa.bench_id) if bsa else None
        if not dep or not bsa or not bench:
            return
        owner_id = bench.user_id
        op = (dep.operation or 'full_site').strip() or 'full_site'

        if dep.status == 'queued':
            _transition_deployment(dep, 'building')
            _stamp_stage(dep, 'building')
        elif dep.status == 'failed':
            _transition_deployment(dep, 'deploying')
            _stamp_stage(dep, 'deploying')
            _append(job, '[pipeline] retry: resuming deploy (remote steps are idempotent)', level='info')
        _transition_job(job, 'running')
        job.attempt_count += 1
        db.commit()

        try:
            if op == 'full_site' and not can_add_site(db, owner_id):
                raise RuntimeError('quota_active_sites exceeded for your plan')

            if dep.status == 'building':
                _transition_deployment(dep, 'deploying')
                _stamp_stage(dep, 'deploying')
            db.commit()

            if op == 'full_site':
                site_domain = deploy_domain_for_app(bsa.name)
                apps_line = apps_csv_for_bench(bsa.name)
                for line, level in stream_theiux_deploy(
                    domain=site_domain,
                    git_repo_url=bsa.git_repo_url,
                    runtime=bsa.runtime,
                    runtime_version=bsa.runtime_version,
                    apps_csv=apps_line,
                ):
                    _append(job, line, level=level)
                    db.commit()
                site_row = db.scalar(select(Site).where(Site.bench_id == bench.id, Site.domain == site_domain))
                if not site_row:
                    site_row = Site(bench_id=bench.id, domain=site_domain, status='active')
                    db.add(site_row)
                    db.commit()
                    db.refresh(site_row)
                _ensure_site_app_link(db, site_row, bsa.id, 'installed')
                ctx = dict(dep.context or {})
                ctx['site_id'] = site_row.id
                dep.context = ctx

            elif op == 'install_app':
                site_id = (dep.context or {}).get('site_id')
                if not site_id:
                    raise RuntimeError('install_app requires context.site_id')
                site_row = db.get(Site, site_id)
                if not site_row or site_row.bench_id != bench.id:
                    raise RuntimeError('site not found or wrong bench')
                git_url = bsa.git_repo_url if bsa.git_repo_url else None
                for line, level in stream_theiux_install_app_on_site(
                    domain=site_row.domain, app_name=bsa.name, git_repo_url=git_url
                ):
                    _append(job, line, level=level)
                    db.commit()
                _ensure_site_app_link(db, site_row, bsa.id, 'installed')

            elif op == 'uninstall_app':
                site_id = (dep.context or {}).get('site_id')
                if not site_id:
                    raise RuntimeError('uninstall_app requires context.site_id')
                site_row = db.get(Site, site_id)
                if not site_row or site_row.bench_id != bench.id:
                    raise RuntimeError('site not found or wrong bench')
                if (bsa.name or '').lower() == 'frappe':
                    raise RuntimeError('refusing to uninstall frappe')
                for line, level in stream_theiux_uninstall_app_from_site(domain=site_row.domain, app_name=bsa.name):
                    _append(job, line, level=level)
                    db.commit()
                link = db.scalar(
                    select(SiteApp).where(SiteApp.site_id == site_row.id, SiteApp.bench_source_app_id == bsa.id)
                )
                if link:
                    db.delete(link)

            elif op == 'get_app_bench':
                for line, level in stream_theiux_get_app_only(bsa.git_repo_url, bsa.git_branch):
                    _append(job, line, level=level)
                    db.commit()
            else:
                raise RuntimeError(f'unknown deployment operation: {op}')

            _append(job, '[pipeline] cli finished successfully', level='info')
            db.commit()
            _transition_deployment(dep, 'success')
            _stamp_stage(dep, 'success')
            _transition_job(job, 'succeeded')
            dep.error_message = None
            dep.last_error_type = None
            job.error_message = None
            job.last_error_type = None
        except Exception as exc:
            category = classify_error(exc)
            prev_stage = dep.status
            if prev_stage in {'building', 'deploying'}:
                _transition_deployment(dep, 'failed')
                _stamp_stage(dep, 'failed')
                m = dict(dep.stage_timestamps or {})
                m['failed_during'] = prev_stage
                dep.stage_timestamps = m
            err_text = _deployment_error_text(exc)
            dep.error_message = err_text
            dep.last_error_type = category
            _transition_job(job, 'failed')
            job.error_message = err_text
            job.last_error_type = category
            _append(job, f'ERROR [{category}]: {exc!s}', level='error')
            db.commit()
            if job.attempt_count < job.max_retries:
                _transition_job(job, 'retrying')
                _append(job, f'Retrying attempt {job.attempt_count + 1} of {job.max_retries}')
            else:
                _transition_job(job, 'dead_letter')
                if dep.status == 'failed':
                    _transition_deployment(dep, 'rollback')
                    _stamp_stage(dep, 'rollback')
                    _append(job, 'Executing rollback after permanent failure', level='error')
                    _transition_deployment(dep, 'stable')
                    _stamp_stage(dep, 'stable')
            record_job(duration_ms=int((time.monotonic() - start) * 1000), success=False, category=category)
        else:
            record_job(duration_ms=int((time.monotonic() - start) * 1000), success=True)
        finally:
            job.duration_ms = int((time.monotonic() - start) * 1000)
        db.commit()
    finally:
        db.close()


def process_bench_sync(bench_id: str) -> None:
    """RQ: refresh git metadata on bench_source_apps and installed flags on site_apps (best-effort)."""
    db: Session = SessionLocal()
    try:
        bench = db.get(Bench, bench_id)
        if not bench:
            return
        bench.last_sync_status = 'running'
        bench.last_sync_error = None
        db.commit()
        now = datetime.now(timezone.utc)
        lines: list[str] = []
        try:
            for line, _level in stream_theiux_inventory_bench():
                lines.append(line)
        except TheiuxDeployError as exc:
            bench.last_sync_status = 'failed'
            bench.last_sync_error = (exc.combined_output or str(exc))[:8000]
            bench.last_sync_at = now
            db.commit()
            return

        for raw in lines:
            if not raw.startswith('source|'):
                continue
            parts = raw.split('|', 4)
            if len(parts) < 5:
                continue
            _tag, name, branch, sha, msg = parts[0], parts[1], parts[2], parts[3], parts[4]
            bsa = db.scalar(
                select(BenchSourceApp).where(
                    BenchSourceApp.bench_id == bench.id,
                    func.lower(BenchSourceApp.name) == name.lower(),
                )
            )
            if bsa:
                bsa.git_branch = branch or None
                bsa.last_commit_sha = sha or None
                bsa.last_commit_message = msg or None
                bsa.synced_at = now
        db.commit()

        sites = list(db.scalars(select(Site).where(Site.bench_id == bench.id)).all())
        for site in sites:
            try:
                installed: set[str] = set()
                for line, _lvl in stream_theiux_inventory_site(site.domain):
                    if line.startswith('installed|'):
                        installed.add(line.split('|', 1)[1].strip().lower())
                for bsa in db.scalars(select(BenchSourceApp).where(BenchSourceApp.bench_id == bench.id)).all():
                    link = db.scalar(
                        select(SiteApp).where(SiteApp.site_id == site.id, SiteApp.bench_source_app_id == bsa.id)
                    )
                    if not link:
                        continue
                    if bsa.name.lower() in installed:
                        link.state = 'installed'
                        link.synced_at = now
                    else:
                        link.state = 'missing_on_site'
                db.commit()
            except TheiuxDeployError:
                continue

        bench.last_sync_status = 'success'
        bench.last_sync_error = None
        bench.last_sync_at = now
        db.commit()
    finally:
        db.close()
