"""Shared helpers for /v1 route modules (benches, sites, core v1)."""

from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.config import settings
from app.curated_presets import CURATED_APP_PRESETS
from app.errors import raise_api_error
from app.models import AppPreset, BenchSourceApp, SiteApp
from app.schemas import AppOut, AppPresetOut, BenchSourceAppOut, SiteAppOut


def slugify_bench(s: str) -> str:
    x = re.sub(r'[^a-z0-9]+', '-', (s or '').lower().strip()).strip('-') or 'bench'
    return x[:60]


def bsa_to_app_out(bsa: BenchSourceApp, user_id: str) -> AppOut:
    return AppOut(
        id=bsa.id,
        user_id=user_id,
        bench_id=bsa.bench_id,
        plan_id=bsa.plan_id,
        name=bsa.name,
        git_repo_url=bsa.git_repo_url,
        git_branch=bsa.git_branch,
        runtime=bsa.runtime,
        runtime_version=bsa.runtime_version,
        last_commit_sha=bsa.last_commit_sha,
        last_commit_message=bsa.last_commit_message,
        synced_at=bsa.synced_at,
        created_at=bsa.created_at,
    )


def bsa_to_source_out(bsa: BenchSourceApp) -> BenchSourceAppOut:
    return BenchSourceAppOut.model_validate(bsa)


def site_apps_out(db: Session, site_id: str) -> list[SiteAppOut]:
    rows = db.execute(
        select(SiteApp, BenchSourceApp)
        .join(BenchSourceApp, SiteApp.bench_source_app_id == BenchSourceApp.id)
        .where(SiteApp.site_id == site_id)
    ).all()
    out: list[SiteAppOut] = []
    for sa, bsa in rows:
        out.append(
            SiteAppOut(
                id=sa.id,
                site_id=sa.site_id,
                bench_source_app_id=sa.bench_source_app_id,
                app_name=bsa.name,
                git_repo_url=bsa.git_repo_url,
                state=sa.state,
                installed_version=sa.installed_version,
                last_commit_sha=sa.last_commit_sha or bsa.last_commit_sha,
                last_commit_message=sa.last_commit_message or bsa.last_commit_message,
                synced_at=sa.synced_at,
            )
        )
    return out


def app_presets_from_db(db: Session) -> list[AppPresetOut] | None:
    try:
        rows = list(db.scalars(select(AppPreset).order_by(AppPreset.sort_order.asc(), AppPreset.slug)).all())
    except OperationalError:
        return None
    if not rows:
        return None
    return [
        AppPresetOut(
            id=r.slug,
            label=r.label,
            description=r.description,
            name=r.name,
            git_repo_url=r.git_repo_url,
            runtime=r.runtime,
            runtime_version=r.runtime_version,
        )
        for r in rows
    ]


def list_app_presets_response(db: Session) -> list[AppPresetOut]:
    from_db = app_presets_from_db(db)
    if from_db is not None:
        return from_db
    out: list[AppPresetOut] = []
    for pid, f in sorted(CURATED_APP_PRESETS.items()):
        out.append(
            AppPresetOut(
                id=pid,
                label=f['label'],
                description=f['description'],
                name=f['name'],
                git_repo_url=f['git_repo_url'],
                runtime=f['runtime'],
                runtime_version=f['runtime_version'],
            )
        )
    return out


def validate_runtime(runtime: str, version: str) -> None:
    allowed = set(settings.allowed_runtime_versions.split(','))
    if f'{runtime}:{version}' not in allowed:
        raise_api_error(
            status_code=400,
            code='runtime_not_allowed',
            message='runtime/version not allowed',
            category='client_error',
            details={'allowed': sorted(allowed)},
        )
