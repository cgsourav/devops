"""Site routes (mounted under /v1)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit_service import write_audit
from app.bench_service import bench_source_app_for_user, site_for_user
from app.deploy_enqueue import check_queue_and_circuit, enqueue_bench_sync, enqueue_new_deployment
from app.deployment_presenter import deployment_to_out
from app.db import get_db
from app.deps import current_user, require_min_role
from app.errors import raise_api_error
from app.jobs import classify_error
from app.models import Bench, Site, User
from app.routers.api_helpers import site_apps_out
from app.schemas import (
    DeploymentOut,
    MigrateSuccessOut,
    SiteAppOut,
    SiteBackupCreateOut,
    SiteBackupOut,
    SiteDetailOut,
    SiteDomainIn,
    SiteDomainOut,
    SiteOut,
    SiteRestoreIn,
    SiteRestoreOut,
)
from app.models import SiteBackup, SiteDomain

router = APIRouter()


@router.get('/sites', response_model=list[SiteOut], tags=['sites'])
def list_sites(db: Session = Depends(get_db), user: User = Depends(current_user)) -> list[Site]:
    return list(db.scalars(select(Site).join(Bench, Site.bench_id == Bench.id).where(Bench.user_id == user.id)).all())


@router.post('/sites/{site_id}/migrate', response_model=MigrateSuccessOut, tags=['sites'])
def run_migration(
    site_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_min_role('admin')),
) -> MigrateSuccessOut:
    site = site_for_user(db, user.id, site_id)
    if not site:
        raise_api_error(status_code=404, code='site_not_found', message='site not found', category='client_error')
    try:
        site.status = 'migrating'
        db.commit()
        site.status = 'active'
        db.commit()
        write_audit(
            db,
            user_id=user.id,
            action='migrate',
            resource_type='site',
            resource_id=site.id,
            metadata={'domain': site.domain},
        )
        db.commit()
        return MigrateSuccessOut(ok=True)
    except Exception as exc:
        category = classify_error(exc)
        raise_api_error(
            status_code=500,
            code='migration_failed',
            message=str(exc),
            category=category,
            details={'site_id': site_id},
        )


@router.delete('/sites/{site_id}', status_code=204, tags=['sites'])
def delete_site(
    site_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_min_role('owner')),
) -> Response:
    site = site_for_user(db, user.id, site_id)
    if not site:
        raise_api_error(status_code=404, code='site_not_found', message='site not found', category='client_error')
    domain = site.domain
    db.delete(site)
    db.commit()
    write_audit(
        db,
        user_id=user.id,
        action='delete_site',
        resource_type='site',
        resource_id=site_id,
        metadata={'domain': domain},
    )
    db.commit()
    return Response(status_code=204)


@router.get('/sites/{site_id}', response_model=SiteDetailOut, tags=['sites'])
def get_site_detail(site_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)) -> SiteDetailOut:
    site = site_for_user(db, user.id, site_id)
    if not site:
        raise_api_error(status_code=404, code='site_not_found', message='site not found', category='client_error')
    return SiteDetailOut(site=site, apps=site_apps_out(db, site.id))


@router.get('/sites/{site_id}/apps', response_model=list[SiteAppOut], tags=['sites'])
def list_site_apps_api(site_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)) -> list[SiteAppOut]:
    site = site_for_user(db, user.id, site_id)
    if not site:
        raise_api_error(status_code=404, code='site_not_found', message='site not found', category='client_error')
    return site_apps_out(db, site.id)


@router.post('/sites/{site_id}/sync', tags=['sites'])
def sync_site_inventory(
    site_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_min_role('admin')),
) -> dict:
    site = site_for_user(db, user.id, site_id)
    if not site:
        raise_api_error(status_code=404, code='site_not_found', message='site not found', category='client_error')
    check_queue_and_circuit()
    enqueue_bench_sync(site.bench_id)
    write_audit(
        db,
        user_id=user.id,
        action='bench_sync',
        resource_type='site',
        resource_id=site_id,
        metadata={'bench_id': site.bench_id, 'via': 'site_sync'},
    )
    db.commit()
    return {'ok': True, 'bench_id': site.bench_id, 'message': 'bench sync job queued for this site\'s bench'}


@router.post('/sites/{site_id}/install-app/{bsa_id}', response_model=DeploymentOut, tags=['sites'])
def enqueue_install_app_on_site(
    site_id: str,
    bsa_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_min_role('admin')),
) -> DeploymentOut:
    site = site_for_user(db, user.id, site_id)
    if not site:
        raise_api_error(status_code=404, code='site_not_found', message='site not found', category='client_error')
    bsa = bench_source_app_for_user(db, user.id, bsa_id)
    if not bsa or bsa.bench_id != site.bench_id:
        raise_api_error(status_code=404, code='app_not_found', message='source app not on this bench', category='client_error')
    dep = enqueue_new_deployment(db, user, bsa, operation='install_app', context={'site_id': site.id})
    return deployment_to_out(dep)


@router.post('/sites/{site_id}/uninstall-app/{bsa_id}', response_model=DeploymentOut, tags=['sites'])
def enqueue_uninstall_app_from_site(
    site_id: str,
    bsa_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_min_role('admin')),
) -> DeploymentOut:
    site = site_for_user(db, user.id, site_id)
    if not site:
        raise_api_error(status_code=404, code='site_not_found', message='site not found', category='client_error')
    bsa = bench_source_app_for_user(db, user.id, bsa_id)
    if not bsa or bsa.bench_id != site.bench_id:
        raise_api_error(status_code=404, code='app_not_found', message='source app not on this bench', category='client_error')
    dep = enqueue_new_deployment(db, user, bsa, operation='uninstall_app', context={'site_id': site.id})
    return deployment_to_out(dep)


@router.get('/sites/{site_id}/domains', response_model=list[SiteDomainOut], tags=['sites'])
def list_site_domains(site_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)) -> list[SiteDomain]:
    site = site_for_user(db, user.id, site_id)
    if not site:
        raise_api_error(status_code=404, code='site_not_found', message='site not found', category='client_error')
    return list(db.scalars(select(SiteDomain).where(SiteDomain.site_id == site_id)).all())


@router.post('/sites/{site_id}/domains', response_model=SiteDomainOut, tags=['sites'])
def add_site_domain(
    site_id: str,
    payload: SiteDomainIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_min_role('admin')),
) -> SiteDomain:
    site = site_for_user(db, user.id, site_id)
    if not site:
        raise_api_error(status_code=404, code='site_not_found', message='site not found', category='client_error')
    row = SiteDomain(site_id=site_id, domain=payload.domain.strip().lower(), verification_status='pending', ssl_status='provisioning')
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.post('/sites/{site_id}/domains/{domain_id}/verify', response_model=SiteDomainOut, tags=['sites'])
def verify_site_domain(
    site_id: str,
    domain_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_min_role('admin')),
) -> SiteDomain:
    site = site_for_user(db, user.id, site_id)
    if not site:
        raise_api_error(status_code=404, code='site_not_found', message='site not found', category='client_error')
    row = db.scalar(select(SiteDomain).where(SiteDomain.id == domain_id, SiteDomain.site_id == site_id))
    if not row:
        raise_api_error(status_code=404, code='domain_not_found', message='domain not found', category='client_error')
    row.verification_status = 'verified'
    row.ssl_status = 'active'
    db.commit()
    db.refresh(row)
    return row


@router.get('/sites/{site_id}/backups', response_model=list[SiteBackupOut], tags=['sites'])
def list_site_backups(site_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)) -> list[SiteBackup]:
    site = site_for_user(db, user.id, site_id)
    if not site:
        raise_api_error(status_code=404, code='site_not_found', message='site not found', category='client_error')
    return list(db.scalars(select(SiteBackup).where(SiteBackup.site_id == site_id).order_by(SiteBackup.created_at.desc())).all())


@router.post('/sites/{site_id}/backups', response_model=SiteBackupCreateOut, tags=['sites'])
def create_site_backup(
    site_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_min_role('admin')),
) -> SiteBackupCreateOut:
    site = site_for_user(db, user.id, site_id)
    if not site:
        raise_api_error(status_code=404, code='site_not_found', message='site not found', category='client_error')
    backup = SiteBackup(site_id=site_id, status='completed', storage_ref=f's3://theiux-backups/{site_id}/{site_id}-{int(site.created_at.timestamp())}.sql.gz', created_by_user_id=user.id)
    db.add(backup)
    db.commit()
    db.refresh(backup)
    return SiteBackupCreateOut(ok=True, backup=backup)


@router.post('/sites/{site_id}/restore', response_model=SiteRestoreOut, tags=['sites'])
def restore_site_from_backup(
    site_id: str,
    payload: SiteRestoreIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_min_role('admin')),
) -> SiteRestoreOut:
    site = site_for_user(db, user.id, site_id)
    if not site:
        raise_api_error(status_code=404, code='site_not_found', message='site not found', category='client_error')
    backup = db.scalar(select(SiteBackup).where(SiteBackup.id == payload.backup_id, SiteBackup.site_id == site_id))
    if not backup:
        raise_api_error(status_code=404, code='backup_not_found', message='backup not found', category='client_error')
    site.status = 'restoring'
    db.commit()
    site.status = 'active'
    db.commit()
    return SiteRestoreOut(ok=True, site_id=site_id, backup_id=backup.id)
