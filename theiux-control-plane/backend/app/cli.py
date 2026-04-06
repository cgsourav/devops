"""Operator CLI (run inside backend container or with PYTHONPATH=.)."""

from __future__ import annotations

import argparse
import getpass
import sys

from fastapi import HTTPException
from sqlalchemy import select

from app.auth import hash_password
from app.config import settings
from app.bench_service import ensure_default_bench
from app.curated_presets import CURATED_APP_PRESETS
from app.db import SessionLocal
from app.deploy_enqueue import enqueue_new_deployment
from app.deps import ROLE_ORDER
from app.models import BenchSourceApp, Plan, User


def cmd_set_password(args: argparse.Namespace) -> None:
    db = SessionLocal()
    try:
        user = db.scalar(select(User).where(User.email == args.email))
        if not user:
            print(f'No user with email: {args.email}', file=sys.stderr)
            raise SystemExit(1)
        if args.password:
            p1 = args.password
        else:
            p1 = getpass.getpass('New password: ')
            p2 = getpass.getpass('Confirm new password: ')
            if p1 != p2:
                print('Passwords do not match.', file=sys.stderr)
                raise SystemExit(1)
        if len(p1) < 8:
            print('Password must be at least 8 characters.', file=sys.stderr)
            raise SystemExit(1)
        user.password_hash = hash_password(p1)
        db.commit()
        print(f'Password updated for {args.email}.')
    finally:
        db.close()


def _assert_runtime_allowed(runtime: str, version: str) -> None:
    allowed = set(settings.allowed_runtime_versions.split(','))
    key = f'{runtime}:{version}'
    if key not in allowed:
        print(f'Runtime {key} not allowed. Allowed: {sorted(allowed)}', file=sys.stderr)
        raise SystemExit(1)


def cmd_enqueue_curated_app(args: argparse.Namespace) -> None:
    """
    Ensure a bench source app for a curated preset on the user's default bench and enqueue full_site (same as POST /v1/deployments).
    Run from the backend container: python -m app.cli enqueue-curated-app --preset erp_lab --email user@example.com
    """
    preset_id = args.preset
    fields = CURATED_APP_PRESETS.get(preset_id)
    if not fields:
        print(f'Unknown preset {preset_id!r}. Known: {", ".join(sorted(CURATED_APP_PRESETS))}', file=sys.stderr)
        raise SystemExit(1)

    db = SessionLocal()
    try:
        user = db.scalar(select(User).where(User.email == args.email.strip()))
        if not user:
            print(f'No user with email: {args.email}', file=sys.stderr)
            raise SystemExit(1)
        role = (user.role or 'viewer').lower()
        if role not in ROLE_ORDER:
            role = 'viewer'
        if ROLE_ORDER[role] < ROLE_ORDER['admin']:
            print(
                'User role must be at least admin (admin or owner) to match API deployment rules.',
                file=sys.stderr,
            )
            raise SystemExit(1)

        if args.plan_name:
            plan = db.scalar(select(Plan).where(Plan.name == args.plan_name))
        else:
            plan = db.scalar(select(Plan).order_by(Plan.price_monthly.asc()))
        if not plan:
            print('No plan in database. Run migrations and seed (plans exist after seed_plans).', file=sys.stderr)
            raise SystemExit(1)

        _assert_runtime_allowed(fields['runtime'], fields['runtime_version'])

        bench = ensure_default_bench(db, user.id)
        bsa = db.scalar(
            select(BenchSourceApp).where(
                BenchSourceApp.bench_id == bench.id,
                BenchSourceApp.name == fields['name'],
            ),
        )
        if bsa:
            if bsa.git_repo_url != fields['git_repo_url']:
                print(
                    f'Source app {fields["name"]!r} exists with different git_repo_url; refusing to reuse.',
                    file=sys.stderr,
                )
                raise SystemExit(1)
        else:
            bsa = BenchSourceApp(
                bench_id=bench.id,
                plan_id=plan.id,
                name=fields['name'],
                git_repo_url=fields['git_repo_url'],
                runtime=fields['runtime'],
                runtime_version=fields['runtime_version'],
            )
            db.add(bsa)
            db.commit()
            db.refresh(bsa)
            print(f'Created bench source app id={bsa.id} name={bsa.name} bench_id={bench.id}')

        if args.app_only:
            print(f'--app-only: skip deploy. app_id={bsa.id}')
            return

        try:
            dep = enqueue_new_deployment(db, user, bsa, operation='full_site', context={})
        except HTTPException as exc:
            detail = exc.detail
            print(f'Enqueue failed ({exc.status_code}): {detail}', file=sys.stderr)
            raise SystemExit(1) from exc
        print(f'Enqueued deployment id={dep.id} app_id={bsa.id}')
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description='Theiux control plane operator commands.')
    sub = parser.add_subparsers(dest='command', required=True)

    sp = sub.add_parser('set-password', help='Set password for a user by email (interactive by default).')
    sp.add_argument('--email', required=True, help='User email')
    sp.add_argument(
        '--password',
        default=None,
        help='New password (avoid in shell history; prefer interactive)',
    )
    sp.set_defaults(func=cmd_set_password)

    sp2 = sub.add_parser(
        'enqueue-curated-app',
        help='Create curated bench source app on default bench and enqueue full_site deploy (same as UI/API).',
    )
    sp2.add_argument('--preset', required=True, help='Preset id (e.g. erp_lab)')
    sp2.add_argument('--email', required=True, help='Existing user email (admin or owner role)')
    sp2.add_argument('--plan-name', default='', help='Plan name (default: cheapest plan)')
    sp2.add_argument(
        '--app-only',
        action='store_true',
        help='Only ensure bench source app exists; do not enqueue deployment',
    )
    sp2.set_defaults(func=cmd_enqueue_curated_app)

    args = parser.parse_args()
    args.func(args)


if __name__ == '__main__':
    main()
