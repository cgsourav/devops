from sqlalchemy import select

from app.auth import hash_password
from app.config import settings
from app.db import SessionLocal
from app.curated_presets import CURATED_APP_PRESETS
from app.models import AppPreset, Plan, User

PLANS = [
    {
        'name': 'Free',
        'price_monthly': 0,
        'cpu_limit': 1,
        'ram_mb': 1024,
        'bandwidth_gb': 50,
        'max_active_sites': 1,
        'max_deployments_per_day': 5,
        'max_concurrent_jobs': 1,
    },
    {
        'name': 'Developer',
        'price_monthly': 10,
        'cpu_limit': 2,
        'ram_mb': 2048,
        'bandwidth_gb': 200,
        'max_active_sites': 3,
        'max_deployments_per_day': 20,
        'max_concurrent_jobs': 2,
    },
    {
        'name': 'Pro',
        'price_monthly': 40,
        'cpu_limit': 4,
        'ram_mb': 8192,
        'bandwidth_gb': 1000,
        'max_active_sites': 10,
        'max_deployments_per_day': 100,
        'max_concurrent_jobs': 5,
    },
]

def seed_plans():
    db = SessionLocal()
    try:
        existing = {p.name for p in db.scalars(select(Plan)).all()}
        for p in PLANS:
            if p['name'] not in existing:
                db.add(Plan(**p))
        db.commit()
    finally:
        db.close()


def seed_app_presets() -> None:
    """Insert app_presets rows from the static registry when missing (idempotent)."""
    db = SessionLocal()
    try:
        existing = {r.slug for r in db.scalars(select(AppPreset)).all()}
        for i, (slug, fields) in enumerate(sorted(CURATED_APP_PRESETS.items())):
            if slug in existing:
                continue
            db.add(
                AppPreset(
                    slug=slug,
                    label=fields['label'],
                    description=fields['description'],
                    name=fields['name'],
                    git_repo_url=fields['git_repo_url'],
                    runtime=fields['runtime'],
                    runtime_version=fields['runtime_version'],
                    sort_order=i,
                )
            )
        db.commit()
    finally:
        db.close()


def seed_bootstrap_admin() -> None:
    """Create platform admin user once if BOOTSTRAP_ADMIN_* env vars are set (API startup only)."""
    email = settings.bootstrap_admin_email
    password = settings.bootstrap_admin_password
    if not email or not password:
        return
    db = SessionLocal()
    try:
        if db.scalar(select(User).where(User.email == email)):
            return
        db.add(User(email=email, password_hash=hash_password(password), role='admin'))
        db.commit()
        print(f'[bootstrap] Created admin user {email} (role=admin). Change password with: python -m app.cli set-password --email {email}', flush=True)
    finally:
        db.close()
