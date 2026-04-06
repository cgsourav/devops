"""Per-plan quota aggregation and enforcement (per user across all bench source apps)."""

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.errors import raise_api_error
from app.models import Bench, BenchSourceApp, Deployment, Job, OrganizationMember, Plan, Site, Subscription, User


def _aggregate_plan_limits(db: Session, user_id: str) -> dict[str, int]:
    """Prefer subscription entitlement; fallback to stacked per-app plans."""
    user = db.get(User, user_id)
    if user and user.default_org_id:
        sub = db.scalar(
            select(Subscription).where(
                Subscription.organization_id == user.default_org_id,
                Subscription.status.in_(('active', 'trialing')),
            )
        )
        if sub:
            plan = db.get(Plan, sub.plan_id)
            if plan:
                return {
                    'max_active_sites': int(plan.max_active_sites or 0),
                    'max_deployments_per_day': int(plan.max_deployments_per_day or 0),
                    'max_concurrent_jobs': int(plan.max_concurrent_jobs or 0),
                }
    elif user:
        org_member = db.scalar(
            select(OrganizationMember).where(OrganizationMember.user_id == user.id).order_by(OrganizationMember.created_at.asc())
        )
        if org_member:
            sub = db.scalar(
                select(Subscription).where(
                    Subscription.organization_id == org_member.organization_id,
                    Subscription.status.in_(('active', 'trialing')),
                )
            )
            if sub:
                plan = db.get(Plan, sub.plan_id)
                if plan:
                    return {
                        'max_active_sites': int(plan.max_active_sites or 0),
                        'max_deployments_per_day': int(plan.max_deployments_per_day or 0),
                        'max_concurrent_jobs': int(plan.max_concurrent_jobs or 0),
                    }

    bsas = list(
        db.scalars(
            select(BenchSourceApp).join(Bench, BenchSourceApp.bench_id == Bench.id).where(Bench.user_id == user_id)
        ).all()
    )
    if not bsas:
        return {'max_active_sites': 0, 'max_deployments_per_day': 0, 'max_concurrent_jobs': 0}
    totals = {'max_active_sites': 0, 'max_deployments_per_day': 0, 'max_concurrent_jobs': 0}
    for bsa in bsas:
        plan = db.get(Plan, bsa.plan_id)
        if not plan:
            continue
        totals['max_active_sites'] += int(plan.max_active_sites or 0)
        totals['max_deployments_per_day'] += int(plan.max_deployments_per_day or 0)
        totals['max_concurrent_jobs'] += int(plan.max_concurrent_jobs or 0)
    return totals


def usage_snapshot(db: Session, user_id: str) -> dict[str, int]:
    start_day = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    sites_n = (
        db.scalar(
            select(func.count())
            .select_from(Site)
            .join(Bench, Site.bench_id == Bench.id)
            .where(Bench.user_id == user_id)
        )
        or 0
    )
    dep_day = (
        db.scalar(
            select(func.count())
            .select_from(Deployment)
            .join(BenchSourceApp, Deployment.bench_source_app_id == BenchSourceApp.id)
            .join(Bench, BenchSourceApp.bench_id == Bench.id)
            .where(Bench.user_id == user_id, Deployment.created_at >= start_day)
        )
        or 0
    )
    concurrent = (
        db.scalar(
            select(func.count())
            .select_from(Job)
            .join(Deployment, Job.deployment_id == Deployment.id)
            .join(BenchSourceApp, Deployment.bench_source_app_id == BenchSourceApp.id)
            .join(Bench, BenchSourceApp.bench_id == Bench.id)
            .where(
                Bench.user_id == user_id,
                Job.status.in_(('queued', 'running', 'retrying')),
            )
        )
        or 0
    )
    return {
        'active_sites': int(sites_n),
        'deployments_today': int(dep_day),
        'concurrent_jobs': int(concurrent),
    }


def can_add_site(db: Session, user_id: str) -> bool:
    """False if user is at or over active site cap (0 = unlimited)."""
    limits = _aggregate_plan_limits(db, user_id)
    use = usage_snapshot(db, user_id)
    if limits['max_active_sites'] <= 0:
        return True
    return use['active_sites'] < limits['max_active_sites']


def enforce_deploy_and_job_quotas(db: Session, user_id: str) -> None:
    """Call before creating a new deployment job (counts current + 1)."""
    limits = _aggregate_plan_limits(db, user_id)
    use = usage_snapshot(db, user_id)
    if limits['max_concurrent_jobs'] > 0 and use['concurrent_jobs'] >= limits['max_concurrent_jobs']:
        raise_api_error(
            status_code=429,
            code='quota_concurrent_jobs',
            message='concurrent job limit reached for your plan',
            category='quota',
            details={'limit': limits['max_concurrent_jobs'], 'usage': use['concurrent_jobs']},
            headers={'Retry-After': '60'},
        )
    if limits['max_deployments_per_day'] > 0 and use['deployments_today'] >= limits['max_deployments_per_day']:
        raise_api_error(
            status_code=429,
            code='quota_deployments_per_day',
            message='daily deployment limit reached for your plan',
            category='quota',
            details={'limit': limits['max_deployments_per_day'], 'usage': use['deployments_today']},
            headers={'Retry-After': '86400'},
        )


def limits_and_usage(db: Session, user_id: str) -> dict:
    limits = _aggregate_plan_limits(db, user_id)
    use = usage_snapshot(db, user_id)
    remaining = {
        'active_sites': max(0, limits['max_active_sites'] - use['active_sites']) if limits['max_active_sites'] > 0 else None,
        'deployments_today': max(0, limits['max_deployments_per_day'] - use['deployments_today'])
        if limits['max_deployments_per_day'] > 0
        else None,
        'concurrent_jobs': max(0, limits['max_concurrent_jobs'] - use['concurrent_jobs'])
        if limits['max_concurrent_jobs'] > 0
        else None,
    }
    return {'limits': limits, 'usage': use, 'remaining': remaining}
