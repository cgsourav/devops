"""Bench and app-preset routes (mounted under /v1)."""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import update, select
from sqlalchemy.orm import Session

from app.audit_service import write_audit
from app.bench_service import bench_source_app_for_user, user_owns_bench
from app.deploy_enqueue import check_queue_and_circuit, enqueue_bench_sync, enqueue_new_deployment
from app.deployment_presenter import deployment_to_out
from app.db import get_db
from app.deps import current_user, require_min_role
from app.errors import raise_api_error
from app.models import Bench, BenchSourceApp, Deployment, Job, OrganizationMember, Site, User
from app.routers.api_helpers import bsa_to_source_out, list_app_presets_response, slugify_bench, validate_runtime
from app.schemas import (
    AppPresetOut,
    BenchCreateIn,
    BenchOut,
    BenchReconcileJobsOut,
    BenchSourceAppCreateIn,
    BenchSourceAppOut,
    DeploymentOut,
    SiteOut,
)

router = APIRouter()


@router.get('/app-presets', response_model=list[AppPresetOut], tags=['apps'])
def list_app_presets(db: Session = Depends(get_db), _: User = Depends(current_user)) -> list[AppPresetOut]:
    return list_app_presets_response(db)


@router.get('/benches', response_model=list[BenchOut], tags=['benches'])
def list_benches(db: Session = Depends(get_db), user: User = Depends(current_user)) -> list[Bench]:
    return list(db.scalars(select(Bench).where(Bench.user_id == user.id).order_by(Bench.created_at.asc())).all())


@router.post('/benches', response_model=BenchOut, tags=['benches'])
def create_bench(
    payload: BenchCreateIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_min_role('owner')),
) -> Bench:
    org_id = user.default_org_id
    if not org_id:
        member = db.scalar(
            select(OrganizationMember).where(OrganizationMember.user_id == user.id).order_by(OrganizationMember.created_at.asc())
        )
        org_id = member.organization_id if member else None
    slug = payload.slug or slugify_bench(payload.name)
    if db.scalar(select(Bench.id).where(Bench.user_id == user.id, Bench.slug == slug)):
        slug = f'{slug}-{secrets.token_hex(3)}'
    b = Bench(
        user_id=user.id,
        organization_id=org_id,
        name=payload.name.strip(),
        slug=slug,
        status='active',
        instance_ref=payload.instance_ref,
        region=payload.region,
    )
    db.add(b)
    db.commit()
    db.refresh(b)
    return b


@router.get('/benches/{bench_id}', response_model=BenchOut, tags=['benches'])
def get_bench(bench_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)) -> Bench:
    if not user_owns_bench(db, user.id, bench_id):
        raise_api_error(status_code=404, code='bench_not_found', message='bench not found', category='client_error')
    b = db.get(Bench, bench_id)
    if not b:
        raise_api_error(status_code=404, code='bench_not_found', message='bench not found', category='client_error')
    return b


@router.post('/benches/{bench_id}/sync', tags=['benches'])
def sync_bench(
    bench_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_min_role('admin')),
) -> dict:
    if not user_owns_bench(db, user.id, bench_id):
        raise_api_error(status_code=404, code='bench_not_found', message='bench not found', category='client_error')
    check_queue_and_circuit()
    enqueue_bench_sync(bench_id)
    write_audit(
        db,
        user_id=user.id,
        action='bench_sync',
        resource_type='bench',
        resource_id=bench_id,
        metadata={},
    )
    db.commit()
    return {'ok': True, 'bench_id': bench_id, 'message': 'sync job queued'}


@router.post('/benches/{bench_id}/reconcile-jobs', response_model=BenchReconcileJobsOut, tags=['benches'])
def reconcile_stuck_bench_jobs(
    bench_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_min_role('admin')),
) -> BenchReconcileJobsOut:
    if not user_owns_bench(db, user.id, bench_id):
        raise_api_error(status_code=404, code='bench_not_found', message='bench not found', category='client_error')
    stale_minutes = 10
    stale_before = datetime.now(timezone.utc) - timedelta(minutes=stale_minutes)
    job_ids = list(
        db.scalars(
            select(Job.id)
            .join(Deployment, Job.deployment_id == Deployment.id)
            .join(BenchSourceApp, Deployment.bench_source_app_id == BenchSourceApp.id)
            .where(BenchSourceApp.bench_id == bench_id, Job.status == 'retrying', Job.updated_at < stale_before)
        ).all()
    )
    reclaimed = 0
    if job_ids:
        result = db.execute(
            update(Job)
            .where(Job.id.in_(job_ids))
            .values(status='dead_letter', updated_at=datetime.now(timezone.utc))
        )
        reclaimed = int(result.rowcount or 0)
    write_audit(
        db,
        user_id=user.id,
        action='reconcile_jobs',
        resource_type='bench',
        resource_id=bench_id,
        metadata={'reclaimed_jobs': reclaimed, 'threshold_minutes': stale_minutes},
    )
    db.commit()
    return BenchReconcileJobsOut(
        ok=True,
        bench_id=bench_id,
        reclaimed_jobs=reclaimed,
        threshold_minutes=stale_minutes,
    )


@router.get('/benches/{bench_id}/source-apps', response_model=list[BenchSourceAppOut], tags=['benches'])
def list_bench_source_apps(
    bench_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)
) -> list[BenchSourceAppOut]:
    if not user_owns_bench(db, user.id, bench_id):
        raise_api_error(status_code=404, code='bench_not_found', message='bench not found', category='client_error')
    bsas = list(db.scalars(select(BenchSourceApp).where(BenchSourceApp.bench_id == bench_id)).all())
    return [bsa_to_source_out(x) for x in bsas]


@router.post('/benches/{bench_id}/source-apps', response_model=BenchSourceAppOut, tags=['benches'])
def create_bench_source_app(
    bench_id: str,
    payload: BenchSourceAppCreateIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_min_role('owner')),
) -> BenchSourceApp:
    if not user_owns_bench(db, user.id, bench_id):
        raise_api_error(status_code=404, code='bench_not_found', message='bench not found', category='client_error')
    validate_runtime(payload.runtime, payload.runtime_version)
    bsa = BenchSourceApp(
        bench_id=bench_id,
        plan_id=payload.plan_id,
        name=payload.name.strip(),
        git_repo_url=payload.git_repo_url.strip(),
        git_branch=payload.git_branch,
        runtime=payload.runtime,
        runtime_version=payload.runtime_version,
    )
    db.add(bsa)
    db.commit()
    db.refresh(bsa)
    return bsa


@router.get('/benches/{bench_id}/sites', response_model=list[SiteOut], tags=['benches'])
def list_bench_sites(bench_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)) -> list[Site]:
    if not user_owns_bench(db, user.id, bench_id):
        raise_api_error(status_code=404, code='bench_not_found', message='bench not found', category='client_error')
    return list(db.scalars(select(Site).where(Site.bench_id == bench_id)).all())


@router.get('/benches/{bench_id}/deployments', response_model=list[DeploymentOut], tags=['benches'])
def list_bench_deployments(bench_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)) -> list[DeploymentOut]:
    if not user_owns_bench(db, user.id, bench_id):
        raise_api_error(status_code=404, code='bench_not_found', message='bench not found', category='client_error')
    rows = list(
        db.scalars(
            select(Deployment)
            .join(BenchSourceApp, Deployment.bench_source_app_id == BenchSourceApp.id)
            .where(BenchSourceApp.bench_id == bench_id)
        ).all()
    )
    return [deployment_to_out(d) for d in rows]


@router.post('/benches/{bench_id}/fetch-app/{bsa_id}', response_model=DeploymentOut, tags=['benches'])
def enqueue_get_app_on_bench(
    bench_id: str,
    bsa_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_min_role('admin')),
) -> DeploymentOut:
    if not user_owns_bench(db, user.id, bench_id):
        raise_api_error(status_code=404, code='bench_not_found', message='bench not found', category='client_error')
    bsa = bench_source_app_for_user(db, user.id, bsa_id)
    if not bsa or bsa.bench_id != bench_id:
        raise_api_error(status_code=404, code='app_not_found', message='source app not found', category='client_error')
    dep = enqueue_new_deployment(db, user, bsa, operation='get_app_bench', context={})
    return deployment_to_out(dep)
