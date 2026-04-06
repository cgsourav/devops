"""Versioned /v1 API routes (OpenAPI tags + response models)."""

from __future__ import annotations

import asyncio
import hashlib
import os
import secrets
import shutil
import subprocess
import time
import threading
import uuid
from pathlib import Path
from urllib.parse import urlparse
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.security import OAuth2PasswordRequestForm
from rq import Retry
from sqlalchemy import desc, select, text
from sqlalchemy.orm import Session

from app.auth import create_access_token, create_refresh_token, decode_token, hash_password, verify_password
from app.config import settings
from app.audit_service import write_audit
from app.bench_service import bench_source_app_for_user, ensure_default_bench, user_owns_bench
from app.deploy_enqueue import check_queue_and_circuit, enforce_deploy_retry_rate_limit, enqueue_new_deployment
from app.deployment_presenter import deployment_to_out
from app.db import get_db
from app.deps import current_user, require_min_role
from app.errors import raise_api_error
from app.observability import metrics_export_payload, worker_status_payload
from app.quotas import enforce_deploy_and_job_quotas, limits_and_usage
from app.jobs import DEPLOYMENT_TRANSITIONS, process_deployment
from app.metrics import snapshot
from app.models import (
    AuditLog,
    Bench,
    BenchSourceApp,
    Deployment,
    Job,
    Organization,
    OrganizationMember,
    Plan,
    RefreshToken,
    Subscription,
    User,
)
from app.queue import queue
from app.theiux_cli import subprocess_env_for_tools
from app.routers import benches as benches_routes
from app.routers import sites as sites_routes
from app.routers.api_helpers import bsa_to_app_out, validate_runtime
from app.schemas import (
    AppCreateIn,
    AppOut,
    AuditLogOut,
    DeploymentCreateIn,
    DeploymentLogsPlainOut,
    DeploymentLogsStructuredOut,
    DeploymentOut,
    DeploymentRetryOut,
    DeploymentTransitionOut,
    HealthOut,
    LimitsOut,
    LogoutIn,
    LogoutOut,
    MetricsExportOut,
    PlanOut,
    RefreshIn,
    RegisterIn,
    RegisterOut,
    TheiuxInitIn,
    TheiuxInitOut,
    TheiuxInitStartOut,
    TheiuxInitStateOut,
    TheiuxInitStatusOut,
    TeamInviteIn,
    TeamInviteOut,
    TeamMemberOut,
    TeamOut,
    TokenOut,
    UserMeOut,
    WorkersStatusOut,
    SubscriptionOut,
    SubscriptionSelectPlanIn,
    SubscriptionSelectPlanOut,
)
router = APIRouter()
router.include_router(benches_routes.router)
router.include_router(sites_routes.router)

_rate_limits: defaultdict[str, deque[float]] = defaultdict(deque)
_init_jobs: dict[str, dict] = {}
_init_jobs_lock = threading.Lock()


def _enforce_auth_rate_limit(request: Request) -> None:
    source = request.client.host if request.client else 'unknown'
    now = time.time()
    window = _rate_limits[source]
    while window and now - window[0] > 60:
        window.popleft()
    if len(window) >= settings.auth_rate_limit_per_minute:
        raise_api_error(
            status_code=429,
            code='auth_rate_limited',
            message='too many auth requests',
            category='rate_limit',
            details={'window_seconds': 60},
            headers={'Retry-After': '60'},
        )
    window.append(now)


def _hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()


def _ua_hash(request: Request | None) -> str | None:
    if not settings.enable_refresh_token_binding or not request:
        return None
    ua = request.headers.get('user-agent') or ''
    return hashlib.sha256(ua.encode('utf-8')).hexdigest()


def _set_csrf_cookie(response: Response) -> None:
    if not settings.auth_secure_cookies:
        return
    csrf = secrets.token_urlsafe(32)
    response.set_cookie(
        'csrf_token',
        csrf,
        httponly=False,
        secure=True,
        samesite='strict',
        path='/',
        max_age=settings.refresh_token_expires_days * 86400,
    )


def _set_auth_cookies(response: Response, access_token: str, refresh_token: str) -> None:
    if not settings.auth_secure_cookies:
        return
    response.set_cookie(
        'access_token',
        access_token,
        httponly=True,
        secure=True,
        samesite='strict',
        path='/',
        max_age=settings.jwt_expires_minutes * 60,
    )
    response.set_cookie(
        'refresh_token',
        refresh_token,
        httponly=True,
        secure=True,
        samesite='strict',
        path='/',
        max_age=settings.refresh_token_expires_days * 86400,
    )
    _set_csrf_cookie(response)


def _issue_tokens(db: Session, user_id: str, request: Request | None) -> TokenOut:
    refresh_token_id = secrets.token_urlsafe(32)
    refresh_token = create_refresh_token(user_id, token_id=refresh_token_id)
    access_token = create_access_token(user_id)
    db.add(
        RefreshToken(
            user_id=user_id,
            token_hash=_hash_token(refresh_token),
            expires_at=datetime.now(timezone.utc) + timedelta(days=settings.refresh_token_expires_days),
            ua_hash=_ua_hash(request),
        )
    )
    db.commit()
    return TokenOut(access_token=access_token, refresh_token=refresh_token, token_type='bearer', token_use='access')


def _transition_deployment(dep: Deployment, next_state: str) -> None:
    allowed = DEPLOYMENT_TRANSITIONS.get(dep.status, set())
    if next_state not in allowed:
        raise_api_error(
            status_code=409,
            code='invalid_state_transition',
            message=f'invalid transition {dep.status}->{next_state}',
            category='client_error',
            details={'from': dep.status, 'to': next_state},
        )
    dep.status = next_state


def health_check(db: Session) -> HealthOut:
    db.execute(text('SELECT 1'))
    return HealthOut(status='ok', metrics=snapshot())


@router.post('/auth/register', response_model=RegisterOut, tags=['auth'])
def register(payload: RegisterIn, request: Request, db: Session = Depends(get_db)) -> RegisterOut:
    _enforce_auth_rate_limit(request)
    if db.scalar(select(User).where(User.email == payload.email)):
        raise_api_error(status_code=409, code='email_exists', message='email already exists', category='client_error')
    user = User(email=payload.email, password_hash=hash_password(payload.password), role='owner')
    db.add(user)
    db.commit()
    db.refresh(user)
    slug = payload.email.split('@', 1)[0].strip().lower().replace('.', '-')[:48] or 'org'
    org = Organization(name=f"{payload.email}'s organization", slug=f'{slug}-{user.id[:8]}', created_by_user_id=user.id)
    db.add(org)
    db.commit()
    db.refresh(org)
    db.add(OrganizationMember(organization_id=org.id, user_id=user.id, role='owner'))
    user.default_org_id = org.id
    db.commit()
    return RegisterOut(id=user.id, email=user.email, role=user.role)


@router.post('/auth/login', response_model=TokenOut, tags=['auth'])
def login(
    request: Request,
    response: Response,
    form: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
) -> TokenOut:
    _enforce_auth_rate_limit(request)
    user = db.scalar(select(User).where(User.email == form.username))
    if not user or not verify_password(form.password, user.password_hash):
        raise_api_error(status_code=401, code='invalid_credentials', message='invalid credentials', category='auth_error')
    tokens = _issue_tokens(db, user.id, request)
    _set_auth_cookies(response, tokens.access_token, tokens.refresh_token or '')
    write_audit(
        db,
        user_id=user.id,
        action='login',
        resource_type='user',
        resource_id=user.id,
        metadata={},
    )
    db.commit()
    return tokens


@router.post('/auth/refresh', response_model=TokenOut, tags=['auth'])
def refresh_token_route(
    payload: RefreshIn,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> TokenOut:
    _enforce_auth_rate_limit(request)
    raw = payload.refresh_token or request.cookies.get('refresh_token')
    if not raw:
        raise_api_error(status_code=401, code='missing_refresh', message='missing refresh token', category='auth_error')
    try:
        decoded = decode_token(raw)
    except Exception:
        raise_api_error(status_code=401, code='invalid_refresh', message='invalid refresh token', category='auth_error')
    scope = str(decoded.get('scope') or decoded.get('type') or '')
    if scope != 'refresh':
        raise_api_error(status_code=401, code='invalid_refresh_scope', message='token is not a refresh token', category='auth_error')
    token_row = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == _hash_token(raw)))
    if not token_row:
        raise_api_error(status_code=401, code='invalid_refresh', message='invalid refresh token', category='auth_error')
    if token_row.revoked_at is not None or token_row.expires_at < datetime.now(timezone.utc):
        raise_api_error(status_code=401, code='refresh_revoked', message='expired or revoked refresh token', category='auth_error')
    if str(decoded.get('sub')) != token_row.user_id:
        raise_api_error(status_code=401, code='refresh_binding', message='refresh token does not match session', category='auth_error')
    if settings.enable_refresh_token_binding and token_row.ua_hash:
        current = _ua_hash(request)
        if not current or current != token_row.ua_hash:
            raise_api_error(status_code=401, code='refresh_binding', message='refresh token binding mismatch', category='auth_error')
    token_row.revoked_at = datetime.now(timezone.utc)
    db.commit()
    tokens = _issue_tokens(db, token_row.user_id, request)
    _set_auth_cookies(response, tokens.access_token, tokens.refresh_token or '')
    return tokens


@router.post('/auth/logout', response_model=LogoutOut, tags=['auth'])
def logout(payload: LogoutIn, request: Request, response: Response, db: Session = Depends(get_db)) -> LogoutOut:
    raw = payload.refresh_token or request.cookies.get('refresh_token')
    if raw:
        token_row = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == _hash_token(raw)))
        if token_row and token_row.revoked_at is None:
            token_row.revoked_at = datetime.now(timezone.utc)
            db.commit()
    if settings.auth_secure_cookies:
        response.delete_cookie('access_token', path='/')
        response.delete_cookie('refresh_token', path='/')
        response.delete_cookie('csrf_token', path='/')
    return LogoutOut()


def _env_for_theiux_init(payload: TheiuxInitIn) -> dict[str, str]:
    """Merge tool PATH with Terraform TF_VAR_* (see https://developer.hashicorp.com/terraform/cli/config/environment-variables#tf_var_name)."""
    env = subprocess_env_for_tools()
    for k, v in payload.model_dump(exclude_none=True).items():
        if isinstance(v, str) and not v.strip():
            continue
        env[f'TF_VAR_{k}'] = str(v)
    return env


def _run_theiux_init_subprocess(payload: TheiuxInitIn) -> tuple[int, str, str]:
    """Execute `theiux init` from the theiux repo root (dirname of bin/theiux → repo root)."""
    cli = Path(settings.theiux_cli_path)
    if not cli.is_file():
        return -1, '', f'theiux CLI not found at {cli}'
    env = _env_for_theiux_init(payload)
    if shutil.which('terraform', path=env.get('PATH')) is None and not Path('/usr/local/bin/terraform').is_file():
        return (
            127,
            '',
            'terraform not found on PATH. Rebuild the backend image (docker compose build --no-cache backend) '
            'or install Terraform on the API host. The slim image installs Terraform under /usr/local/bin.',
        )
    root = cli.resolve().parent.parent
    try:
        proc = subprocess.run(
            [str(cli), 'init'],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=settings.theiux_init_timeout_seconds,
            env=env,
        )
        return proc.returncode, proc.stdout or '', proc.stderr or ''
    except subprocess.TimeoutExpired as e:
        out = e.stdout if isinstance(e.stdout, str) else ''
        err = (e.stderr if isinstance(e.stderr, str) else '') + f'\n[timeout after {settings.theiux_init_timeout_seconds}s]'
        return -1, out, err


def _theiux_context_path() -> Path:
    cli = Path(settings.theiux_cli_path)
    return cli.resolve().parent.parent / 'bin' / '.theiux-context'


def _append_init_log(job_id: str, line: str) -> None:
    with _init_jobs_lock:
        j = _init_jobs.get(job_id)
        if not j:
            return
        logs = j.setdefault('logs', [])
        logs.append(line.rstrip('\n'))
        if len(logs) > 5000:
            del logs[: len(logs) - 5000]


def _run_theiux_init_streaming(job_id: str, payload: TheiuxInitIn) -> None:
    with _init_jobs_lock:
        j = _init_jobs.get(job_id)
        if not j:
            return
        j['status'] = 'running'
        j['started_at'] = datetime.now(timezone.utc).isoformat()

    cli = Path(settings.theiux_cli_path)
    if not cli.is_file():
        with _init_jobs_lock:
            j = _init_jobs.get(job_id)
            if j:
                j['status'] = 'failed'
                j['finished_at'] = datetime.now(timezone.utc).isoformat()
                j['exit_code'] = -1
                j['ok'] = False
                j['stderr'] = f'theiux CLI not found at {cli}'
        return

    env = _env_for_theiux_init(payload)
    root = cli.resolve().parent.parent
    stdout_lines: list[str] = []
    stderr_lines: list[str] = []
    try:
        proc = subprocess.Popen(
            [str(cli), 'init'],
            cwd=str(root),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
    except Exception as exc:
        with _init_jobs_lock:
            j = _init_jobs.get(job_id)
            if j:
                j['status'] = 'failed'
                j['finished_at'] = datetime.now(timezone.utc).isoformat()
                j['exit_code'] = -1
                j['ok'] = False
                j['stderr'] = str(exc)
        return

    def _read_stream(stream, sink: list[str], prefix: str) -> None:
        if not stream:
            return
        for line in stream:
            sink.append(line)
            _append_init_log(job_id, f'[{prefix}] {line.rstrip()}')

    t_out = threading.Thread(target=_read_stream, args=(proc.stdout, stdout_lines, 'stdout'), daemon=True)
    t_err = threading.Thread(target=_read_stream, args=(proc.stderr, stderr_lines, 'stderr'), daemon=True)
    t_out.start()
    t_err.start()
    t_out.join(timeout=settings.theiux_init_timeout_seconds + 30)
    t_err.join(timeout=settings.theiux_init_timeout_seconds + 30)
    try:
        rc = proc.wait(timeout=settings.theiux_init_timeout_seconds)
    except subprocess.TimeoutExpired:
        proc.kill()
        rc = -1
        stderr_lines.append(f'[timeout after {settings.theiux_init_timeout_seconds}s]\n')
        _append_init_log(job_id, f'[stderr] [timeout after {settings.theiux_init_timeout_seconds}s]')

    out = ''.join(stdout_lines)
    err = ''.join(stderr_lines)
    with _init_jobs_lock:
        j = _init_jobs.get(job_id)
        if j:
            j['status'] = 'finished'
            j['finished_at'] = datetime.now(timezone.utc).isoformat()
            j['exit_code'] = rc
            j['ok'] = rc == 0
            j['stdout'] = out
            j['stderr'] = err


@router.get('/me', response_model=UserMeOut, tags=['auth'])
def read_current_user(user: User = Depends(current_user)) -> UserMeOut:
    return UserMeOut(id=user.id, email=user.email, role=user.role or 'viewer', default_org_id=user.default_org_id)


@router.post('/admin/theiux-init', response_model=TheiuxInitOut, tags=['admin'])
async def admin_theiux_init(
    payload: TheiuxInitIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_min_role('admin')),
) -> TheiuxInitOut:
    """
    Run `theiux init` (Terraform apply, writes `bin/.theiux-context`).

    **Body:** Terraform variables required by `theiux/terraform` (at minimum `aws_region` and `repo_url`); passed as `TF_VAR_*`.

    **Authorization:** `admin` or `owner` role only (`viewer` is rejected). Same threshold as creating deployments.

    **Runtime:** The API process must have `terraform` and `aws` on `PATH`, plus AWS credentials (env or mounted config).
    """
    exit_code, out, err = await asyncio.to_thread(_run_theiux_init_subprocess, payload)
    ok = exit_code == 0
    repo_hint = (
        urlparse(payload.repo_url.strip()).netloc
        if payload.repo_url.strip().startswith('http')
        else payload.repo_url.strip().split('@', 1)[-1].split(':', 1)[0]
        if '@' in payload.repo_url
        else 'git'
    )
    write_audit(
        db,
        user_id=user.id,
        action='theiux_init',
        resource_type='platform',
        resource_id=None,
        metadata={
            'exit_code': exit_code,
            'ok': ok,
            'aws_region': payload.aws_region,
            'repo_host': repo_hint,
        },
    )
    db.commit()
    return TheiuxInitOut(ok=ok, exit_code=exit_code, stdout=out, stderr=err)


@router.post('/admin/theiux-init/start', response_model=TheiuxInitStartOut, tags=['admin'])
async def admin_theiux_init_start(
    payload: TheiuxInitIn,
    _: Session = Depends(get_db),
    user: User = Depends(require_min_role('admin')),
) -> TheiuxInitStartOut:
    job_id = str(uuid.uuid4())
    with _init_jobs_lock:
        _init_jobs[job_id] = {
            'job_id': job_id,
            'user_id': user.id,
            'status': 'queued',
            'started_at': None,
            'finished_at': None,
            'exit_code': None,
            'ok': None,
            'logs': [],
            'stdout': '',
            'stderr': '',
            'audited': False,
        }
    threading.Thread(target=_run_theiux_init_streaming, args=(job_id, payload), daemon=True).start()
    return TheiuxInitStartOut(job_id=job_id, status='queued')


@router.get('/admin/theiux-init/state', response_model=TheiuxInitStateOut, tags=['admin'])
def admin_theiux_init_state(
    db: Session = Depends(get_db),
    user: User = Depends(require_min_role('admin')),
) -> TheiuxInitStateOut:
    context_path = _theiux_context_path()
    context_exists = context_path.is_file()

    last_success_at: str | None = None
    last_success_exit_code: int | None = None
    recent = list(
        db.scalars(
            select(AuditLog)
            .where(AuditLog.action == 'theiux_init', AuditLog.user_id == user.id)
            .order_by(desc(AuditLog.created_at))
            .limit(25)
        ).all()
    )
    for row in recent:
        meta = row.meta or {}
        if bool(meta.get('ok')) is True:
            last_success_at = row.created_at.isoformat() if row.created_at else None
            raw_exit = meta.get('exit_code')
            if isinstance(raw_exit, int):
                last_success_exit_code = raw_exit
            elif isinstance(raw_exit, str) and raw_exit.isdigit():
                last_success_exit_code = int(raw_exit)
            else:
                last_success_exit_code = None
            break

    return TheiuxInitStateOut(
        context_file_exists=context_exists,
        context_file_path=str(context_path),
        last_success_at=last_success_at,
        last_success_exit_code=last_success_exit_code,
        is_initialized=context_exists,
    )


@router.get('/admin/theiux-init/{job_id}', response_model=TheiuxInitStatusOut, tags=['admin'])
def admin_theiux_init_status(
    job_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_min_role('admin')),
) -> TheiuxInitStatusOut:
    with _init_jobs_lock:
        j = _init_jobs.get(job_id)
        if not j or j.get('user_id') != user.id:
            raise_api_error(status_code=404, code='init_job_not_found', message='init job not found', category='client_error')
        out = TheiuxInitStatusOut(
            job_id=j['job_id'],
            status=j.get('status', 'unknown'),
            started_at=j.get('started_at'),
            finished_at=j.get('finished_at'),
            exit_code=j.get('exit_code'),
            ok=j.get('ok'),
            logs=list(j.get('logs', []))[-200:],
            stdout=j.get('stdout', ''),
            stderr=j.get('stderr', ''),
        )
        if j.get('status') == 'finished' and not j.get('audited'):
            write_audit(
                db,
                user_id=user.id,
                action='theiux_init',
                resource_type='platform',
                resource_id=None,
                metadata={'exit_code': j.get('exit_code'), 'ok': bool(j.get('ok'))},
            )
            db.commit()
            j['audited'] = True
        return out


@router.get('/plans', response_model=list[PlanOut], tags=['plans'])
def list_plans(db: Session = Depends(get_db), _: User = Depends(current_user)) -> list[Plan]:
    return list(db.scalars(select(Plan)).all())


def _resolve_current_org(db: Session, user: User) -> Organization:
    org_id = user.default_org_id
    if org_id:
        org = db.get(Organization, org_id)
        if org:
            return org
    member = db.scalar(select(OrganizationMember).where(OrganizationMember.user_id == user.id).order_by(OrganizationMember.created_at.asc()))
    if member:
        org = db.get(Organization, member.organization_id)
        if org:
            if user.default_org_id != org.id:
                user.default_org_id = org.id
                db.commit()
            return org
    org = Organization(name=f'{user.email} organization', slug=f'org-{user.id[:8]}', created_by_user_id=user.id)
    db.add(org)
    db.commit()
    db.refresh(org)
    db.add(OrganizationMember(organization_id=org.id, user_id=user.id, role='owner'))
    user.default_org_id = org.id
    db.commit()
    return org


@router.get('/team', response_model=TeamOut, tags=['team'])
def team_overview(db: Session = Depends(get_db), user: User = Depends(current_user)) -> TeamOut:
    org = _resolve_current_org(db, user)
    members = list(db.scalars(select(OrganizationMember).where(OrganizationMember.organization_id == org.id)).all())
    users = {u.id: u for u in db.scalars(select(User).where(User.id.in_([m.user_id for m in members]))).all()} if members else {}
    out = [
        TeamMemberOut(
            user_id=m.user_id,
            email=(users.get(m.user_id).email if users.get(m.user_id) else 'unknown'),
            role=m.role,
            joined_at=m.created_at,
        )
        for m in members
    ]
    return TeamOut(organization_id=org.id, organization_name=org.name, members=out)


@router.post('/team/invite', response_model=TeamInviteOut, tags=['team'])
def invite_team_member(
    payload: TeamInviteIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_min_role('owner')),
) -> TeamInviteOut:
    org = _resolve_current_org(db, user)
    target = db.scalar(select(User).where(User.email == payload.email))
    if not target:
        target = User(email=payload.email, password_hash=hash_password(secrets.token_urlsafe(24)), role='viewer')
        db.add(target)
        db.commit()
        db.refresh(target)
    existing = db.scalar(select(OrganizationMember).where(OrganizationMember.organization_id == org.id, OrganizationMember.user_id == target.id))
    if existing:
        existing.role = payload.role
    else:
        db.add(OrganizationMember(organization_id=org.id, user_id=target.id, role=payload.role))
    db.commit()
    return TeamInviteOut(ok=True, user_id=target.id, role=payload.role)


@router.get('/billing/subscription', response_model=SubscriptionOut, tags=['billing'])
def billing_subscription(db: Session = Depends(get_db), user: User = Depends(current_user)) -> SubscriptionOut:
    org = _resolve_current_org(db, user)
    sub = db.scalar(select(Subscription).where(Subscription.organization_id == org.id))
    if not sub:
        return SubscriptionOut(status='inactive', organization_id=org.id)
    return SubscriptionOut(
        id=sub.id,
        organization_id=sub.organization_id,
        plan_id=sub.plan_id,
        status=sub.status,
        provider=sub.provider,
        trial_ends_at=sub.trial_ends_at,
        current_period_ends_at=sub.current_period_ends_at,
    )


@router.post('/billing/subscription/select-plan', response_model=SubscriptionSelectPlanOut, tags=['billing'])
def billing_select_plan(
    payload: SubscriptionSelectPlanIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_min_role('owner')),
) -> SubscriptionSelectPlanOut:
    plan = db.get(Plan, payload.plan_id)
    if not plan:
        raise_api_error(status_code=404, code='plan_not_found', message='plan not found', category='client_error')
    org = _resolve_current_org(db, user)
    sub = db.scalar(select(Subscription).where(Subscription.organization_id == org.id))
    if not sub:
        sub = Subscription(organization_id=org.id, plan_id=plan.id, status='active', provider='manual')
        db.add(sub)
    else:
        sub.plan_id = plan.id
        sub.status = 'active'
    db.commit()
    db.refresh(sub)
    out = SubscriptionOut(
        id=sub.id,
        organization_id=sub.organization_id,
        plan_id=sub.plan_id,
        status=sub.status,
        provider=sub.provider,
        trial_ends_at=sub.trial_ends_at,
        current_period_ends_at=sub.current_period_ends_at,
    )
    return SubscriptionSelectPlanOut(ok=True, subscription=out)


@router.post('/apps', response_model=AppOut, tags=['apps'])
def create_app(
    payload: AppCreateIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_min_role('owner')),
) -> AppOut:
    validate_runtime(payload.runtime, payload.runtime_version)
    data = payload.model_dump(exclude={'bench_id'}, exclude_none=False)
    bench_id = payload.bench_id
    if bench_id:
        if not user_owns_bench(db, user.id, bench_id):
            raise_api_error(status_code=404, code='bench_not_found', message='bench not found', category='client_error')
        bench = db.get(Bench, bench_id)
    else:
        bench = ensure_default_bench(db, user.id)
    bsa = BenchSourceApp(
        bench_id=bench.id,
        plan_id=data['plan_id'],
        name=data['name'],
        git_repo_url=data['git_repo_url'],
        git_branch=data.get('git_branch'),
        runtime=data['runtime'],
        runtime_version=data['runtime_version'],
    )
    db.add(bsa)
    db.commit()
    db.refresh(bsa)
    return bsa_to_app_out(bsa, user.id)


@router.get('/apps', response_model=list[AppOut], tags=['apps'])
def list_apps(db: Session = Depends(get_db), user: User = Depends(current_user)) -> list[AppOut]:
    bsas = list(
        db.scalars(
            select(BenchSourceApp).join(Bench, BenchSourceApp.bench_id == Bench.id).where(Bench.user_id == user.id)
        ).all()
    )
    return [bsa_to_app_out(b, user.id) for b in bsas]


@router.post('/deployments', response_model=DeploymentOut, tags=['deployments'])
def create_deployment(
    payload: DeploymentCreateIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_min_role('admin')),
) -> DeploymentOut:
    bsa = bench_source_app_for_user(db, user.id, payload.app_id)
    if not bsa:
        raise_api_error(status_code=404, code='app_not_found', message='app not found', category='client_error')
    dep = enqueue_new_deployment(db, user, bsa, operation='full_site', context={})
    return deployment_to_out(dep)


@router.get('/deployments', response_model=list[DeploymentOut], tags=['deployments'])
def list_deployments(db: Session = Depends(get_db), user: User = Depends(current_user)) -> list[DeploymentOut]:
    rows = list(
        db.scalars(
            select(Deployment)
            .join(BenchSourceApp, Deployment.bench_source_app_id == BenchSourceApp.id)
            .join(Bench, BenchSourceApp.bench_id == Bench.id)
            .where(Bench.user_id == user.id)
        ).all()
    )
    return [deployment_to_out(d) for d in rows]


@router.get(
    '/deployments/{deployment_id}/logs',
    response_model=DeploymentLogsPlainOut,
    tags=['logs'],
)
def deployment_logs(
    deployment_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> DeploymentLogsPlainOut:
    dep = db.scalar(
        select(Deployment)
        .join(BenchSourceApp, Deployment.bench_source_app_id == BenchSourceApp.id)
        .join(Bench, BenchSourceApp.bench_id == Bench.id)
        .where(Deployment.id == deployment_id, Bench.user_id == user.id)
    )
    if not dep:
        raise_api_error(status_code=404, code='deployment_not_found', message='deployment not found', category='client_error')
    job = db.scalar(select(Job).where(Job.deployment_id == dep.id))
    lines = job.logs.splitlines() if job and job.logs else []
    return DeploymentLogsPlainOut(
        status=dep.status,
        error_message=dep.error_message,
        last_error_type=dep.last_error_type,
        lines=lines,
    )


@router.get(
    '/deployments/{deployment_id}/logs/structured',
    response_model=DeploymentLogsStructuredOut,
    tags=['logs'],
)
def deployment_logs_structured(
    deployment_id: str,
    offset: int = Query(0, ge=0, description='Pagination offset into structured log entries'),
    limit: int = Query(100, ge=1, le=500, description='Page size (max 500)'),
    errors_only: bool = Query(False, description='If true, only entries with level=error'),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> DeploymentLogsStructuredOut:
    dep = db.scalar(
        select(Deployment)
        .join(BenchSourceApp, Deployment.bench_source_app_id == BenchSourceApp.id)
        .join(Bench, BenchSourceApp.bench_id == Bench.id)
        .where(Deployment.id == deployment_id, Bench.user_id == user.id)
    )
    if not dep:
        raise_api_error(status_code=404, code='deployment_not_found', message='deployment not found', category='client_error')
    job = db.scalar(select(Job).where(Job.deployment_id == dep.id))
    logs = list(job.logs_json or []) if job else []
    if errors_only:
        logs = [entry for entry in logs if str(entry.get('level', '')).lower() == 'error']
    paged = logs[offset : offset + min(limit, 500)]
    return DeploymentLogsStructuredOut(
        status=dep.status,
        total=len(logs),
        offset=offset,
        limit=min(limit, 500),
        entries=paged,
    )


@router.post('/deployments/{deployment_id}/retry', response_model=DeploymentRetryOut, tags=['deployments'])
def retry_failed_deployment(
    deployment_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_min_role('admin')),
) -> DeploymentRetryOut:
    enforce_deploy_retry_rate_limit(user.id)
    check_queue_and_circuit()
    dep = db.scalar(
        select(Deployment)
        .join(BenchSourceApp, Deployment.bench_source_app_id == BenchSourceApp.id)
        .join(Bench, BenchSourceApp.bench_id == Bench.id)
        .where(Deployment.id == deployment_id, Bench.user_id == user.id)
    )
    if not dep:
        raise_api_error(status_code=404, code='deployment_not_found', message='deployment not found', category='client_error')
    job = db.scalar(select(Job).where(Job.deployment_id == dep.id))
    if not job:
        raise_api_error(status_code=404, code='job_not_found', message='job not found', category='client_error')
    if job.status not in {'failed', 'retrying', 'dead_letter'}:
        raise_api_error(status_code=409, code='job_not_retryable', message='job not retryable', category='client_error', details={'status': job.status})
    enforce_deploy_and_job_quotas(db, user.id)
    queued_at = datetime.now(timezone.utc).isoformat()
    new_dep = Deployment(
        bench_source_app_id=dep.bench_source_app_id,
        operation=dep.operation or 'full_site',
        context=dict(dep.context or {}),
        status='queued',
        stage_timestamps={'queued': queued_at},
    )
    db.add(new_dep)
    db.commit()
    db.refresh(new_dep)
    new_job = Job(
        deployment_id=new_dep.id,
        type='deploy',
        status='queued',
        logs='',
        logs_json=[],
        idempotency_key=f'deploy:{new_dep.id}',
        max_retries=3,
    )
    db.add(new_job)
    db.commit()
    db.refresh(new_job)
    queue.enqueue(process_deployment, new_job.id, retry=Retry(max=3, interval=[10, 30, 90]))
    write_audit(
        db,
        user_id=user.id,
        action='retry',
        resource_type='deployment',
        resource_id=new_dep.id,
        metadata={'previous_deployment_id': deployment_id, 'job_id': new_job.id},
    )
    db.commit()
    return DeploymentRetryOut(ok=True, deployment_id=new_dep.id, job_id=new_job.id)


@router.post('/deployments/{deployment_id}/transition/{next_state}', response_model=DeploymentTransitionOut, tags=['deployments'])
def transition_deployment(
    deployment_id: str,
    next_state: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_min_role('owner')),
) -> DeploymentTransitionOut:
    dep = db.scalar(
        select(Deployment)
        .join(BenchSourceApp, Deployment.bench_source_app_id == BenchSourceApp.id)
        .join(Bench, BenchSourceApp.bench_id == Bench.id)
        .where(Deployment.id == deployment_id, Bench.user_id == user.id)
    )
    if not dep:
        raise_api_error(status_code=404, code='deployment_not_found', message='deployment not found', category='client_error')
    _transition_deployment(dep, next_state)
    db.commit()
    return DeploymentTransitionOut(id=dep.id, status=dep.status)


@router.get('/audit', response_model=list[AuditLogOut], tags=['audit'])
def list_audit_logs(
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> list[AuditLog]:
    q = (
        select(AuditLog)
        .where(AuditLog.user_id == user.id)
        .order_by(AuditLog.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    return list(db.scalars(q).all())


@router.get('/health', response_model=HealthOut, tags=['system'])
def health_route(db: Session = Depends(get_db)) -> HealthOut:
    return health_check(db)


@router.get('/metrics', response_model=MetricsExportOut, tags=['system'])
def metrics_export(_: User = Depends(current_user)) -> MetricsExportOut:
    return MetricsExportOut(**metrics_export_payload())


@router.get('/workers/status', response_model=WorkersStatusOut, tags=['system'])
def workers_status(_: User = Depends(current_user)) -> WorkersStatusOut:
    return WorkersStatusOut(**worker_status_payload())


@router.get('/limits', response_model=LimitsOut, tags=['plans'])
def limits_overview(db: Session = Depends(get_db), user: User = Depends(current_user)) -> LimitsOut:
    data = limits_and_usage(db, user.id)
    return LimitsOut(**data)
