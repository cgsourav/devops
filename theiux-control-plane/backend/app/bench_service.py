"""Bench / source-app helpers."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Bench, BenchSourceApp, OrganizationMember, User


def ensure_default_bench(db: Session, user_id: str) -> Bench:
    existing = db.scalar(select(Bench).where(Bench.user_id == user_id).order_by(Bench.created_at.asc()))
    if existing:
        return existing
    import uuid

    bid = str(uuid.uuid4())
    user = db.get(User, user_id)
    org_id = user.default_org_id if user else None
    if not org_id:
        member = db.scalar(
            select(OrganizationMember).where(OrganizationMember.user_id == user_id).order_by(OrganizationMember.created_at.asc())
        )
        org_id = member.organization_id if member else None
    b = Bench(id=bid, user_id=user_id, organization_id=org_id, name='Default', slug='default', status='active')
    db.add(b)
    db.commit()
    db.refresh(b)
    return b


def user_owns_bench(db: Session, user_id: str, bench_id: str) -> bool:
    return (
        db.scalar(select(Bench.id).where(Bench.id == bench_id, Bench.user_id == user_id)) is not None
    )


def bench_source_app_for_user(db: Session, user_id: str, bsa_id: str) -> BenchSourceApp | None:
    return db.scalar(
        select(BenchSourceApp)
        .join(Bench, BenchSourceApp.bench_id == Bench.id)
        .where(BenchSourceApp.id == bsa_id, Bench.user_id == user_id)
    )


def site_for_user(db: Session, user_id: str, site_id: str):
    from app.models import Site

    return db.scalar(
        select(Site).join(Bench, Site.bench_id == Bench.id).where(Site.id == site_id, Bench.user_id == user_id)
    )
