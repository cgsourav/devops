"""Bench / bench_source_apps / site_apps; migrate from apps-centric model."""

from __future__ import annotations

import uuid
from collections import defaultdict

import sqlalchemy as sa
from alembic import op
from sqlalchemy import text

revision = '20260406_0006'
down_revision = '20260325_0005'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'benches',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('user_id', sa.String(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('slug', sa.String(), nullable=False),
        sa.Column('status', sa.String(), nullable=False, server_default='active'),
        sa.Column('instance_ref', sa.String(), nullable=True),
        sa.Column('region', sa.String(), nullable=True),
        sa.Column('last_sync_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_sync_status', sa.String(), nullable=True),
        sa.Column('last_sync_error', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.UniqueConstraint('user_id', 'slug', name='uq_benches_user_slug'),
    )
    op.create_index('ix_benches_user_id', 'benches', ['user_id'])

    op.create_table(
        'bench_source_apps',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('bench_id', sa.String(), sa.ForeignKey('benches.id', ondelete='CASCADE'), nullable=False),
        sa.Column('plan_id', sa.String(), sa.ForeignKey('plans.id'), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('git_repo_url', sa.String(), nullable=False),
        sa.Column('git_branch', sa.String(), nullable=True),
        sa.Column('runtime', sa.String(), nullable=False),
        sa.Column('runtime_version', sa.String(), nullable=False),
        sa.Column('last_commit_sha', sa.String(), nullable=True),
        sa.Column('last_commit_message', sa.Text(), nullable=True),
        sa.Column('synced_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.UniqueConstraint('bench_id', 'name', name='uq_bench_source_apps_bench_name'),
    )
    op.create_index('ix_bench_source_apps_bench_id', 'bench_source_apps', ['bench_id'])

    op.create_table(
        'site_apps',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('site_id', sa.String(), sa.ForeignKey('sites.id', ondelete='CASCADE'), nullable=False),
        sa.Column('bench_source_app_id', sa.String(), sa.ForeignKey('bench_source_apps.id', ondelete='CASCADE'), nullable=False),
        sa.Column('state', sa.String(), nullable=False, server_default='installed'),
        sa.Column('installed_version', sa.String(), nullable=True),
        sa.Column('last_commit_sha', sa.String(), nullable=True),
        sa.Column('last_commit_message', sa.Text(), nullable=True),
        sa.Column('synced_at', sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint('site_id', 'bench_source_app_id', name='uq_site_apps_site_app'),
    )
    op.create_index('ix_site_apps_site_id', 'site_apps', ['site_id'])

    op.add_column('sites', sa.Column('bench_id', sa.String(), nullable=True))
    op.create_foreign_key('fk_sites_bench_id', 'sites', 'benches', ['bench_id'], ['id'], ondelete='CASCADE')

    op.add_column(
        'deployments',
        sa.Column('bench_source_app_id', sa.String(), sa.ForeignKey('bench_source_apps.id', ondelete='CASCADE'), nullable=True),
    )
    op.add_column(
        'deployments',
        sa.Column('operation', sa.String(), nullable=False, server_default='full_site'),
    )
    op.add_column(
        'deployments',
        sa.Column('context', sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
    )

    conn = op.get_bind()

    rows = conn.execute(text('SELECT id, user_id, plan_id, name, git_repo_url, runtime, runtime_version, created_at FROM apps')).mappings().all()
    bench_by_user: dict[str, str] = {}
    app_to_bsa: dict[str, str] = {}
    names_per_bench: dict[str, set[str]] = defaultdict(set)

    for r in rows:
        uid = r['user_id']
        if uid not in bench_by_user:
            bid = str(uuid.uuid4())
            bench_by_user[uid] = bid
            slug = 'default'
            conn.execute(
                text(
                    """
                    INSERT INTO benches (id, user_id, name, slug, status)
                    VALUES (:id, :uid, 'Default', :slug, 'active')
                    """
                ),
                {'id': bid, 'uid': uid, 'slug': slug},
            )
        bid = bench_by_user[uid]
        bsa_id = str(uuid.uuid4())
        app_to_bsa[r['id']] = bsa_id
        nm = (r['name'] or 'app').strip() or 'app'
        if nm in names_per_bench[bid]:
            nm = f'{nm}_{r["id"][:8]}'
        names_per_bench[bid].add(nm)
        conn.execute(
            text(
                """
                INSERT INTO bench_source_apps (id, bench_id, plan_id, name, git_repo_url, git_branch, runtime, runtime_version, last_commit_sha, last_commit_message, synced_at, created_at)
                VALUES (:id, :bid, :pid, :name, :url, NULL, :rt, :rtv, NULL, NULL, NULL, :created_at)
                """
            ),
            {
                'id': bsa_id,
                'bid': bid,
                'pid': r['plan_id'],
                'name': nm,
                'url': r['git_repo_url'],
                'rt': r['runtime'],
                'rtv': r['runtime_version'],
                'created_at': r['created_at'],
            },
        )

    for old_aid, bsa_id in app_to_bsa.items():
        conn.execute(
            text('UPDATE deployments SET bench_source_app_id = :bsa WHERE app_id = :aid'),
            {'bsa': bsa_id, 'aid': old_aid},
        )

    site_rows = conn.execute(text('SELECT id, app_id FROM sites')).mappings().all()
    for s in site_rows:
        aid = s['app_id']
        bsa_id = app_to_bsa.get(aid)
        if not bsa_id:
            continue
        bench_id = conn.execute(
            text('SELECT bench_id FROM bench_source_apps WHERE id = :id'),
            {'id': bsa_id},
        ).scalar()
        conn.execute(
            text('UPDATE sites SET bench_id = :bid WHERE id = :sid'),
            {'bid': bench_id, 'sid': s['id']},
        )
        sa_id = str(uuid.uuid4())
        conn.execute(
            text(
                """
                INSERT INTO site_apps (id, site_id, bench_source_app_id, state)
                VALUES (:id, :sid, :bsa, 'installed')
                """
            ),
            {'id': sa_id, 'sid': s['id'], 'bsa': bsa_id},
        )

    op.alter_column('deployments', 'bench_source_app_id', nullable=False)

    op.drop_constraint('deployments_app_id_fkey', 'deployments', type_='foreignkey')
    op.drop_column('deployments', 'app_id')

    op.drop_constraint('sites_app_id_fkey', 'sites', type_='foreignkey')
    op.drop_column('sites', 'app_id')

    op.alter_column('sites', 'bench_id', nullable=False)

    op.drop_table('apps')


def downgrade() -> None:
    raise NotImplementedError('Downgrade not supported for bench migration')
