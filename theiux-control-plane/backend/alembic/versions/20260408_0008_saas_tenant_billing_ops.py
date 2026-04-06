"""SaaS foundations: org/team, subscriptions, domains, backups."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = '20260408_0008'
down_revision = '20260407_0007'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'organizations',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('slug', sa.String(), nullable=False, unique=True),
        sa.Column('created_by_user_id', sa.String(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
    )
    op.create_table(
        'organization_members',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('organization_id', sa.String(), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('user_id', sa.String(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('role', sa.String(), nullable=False, server_default='viewer'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.UniqueConstraint('organization_id', 'user_id', name='uq_org_member'),
    )
    op.add_column('users', sa.Column('default_org_id', sa.String(), nullable=True))
    op.create_foreign_key('fk_users_default_org_id', 'users', 'organizations', ['default_org_id'], ['id'], ondelete='SET NULL')

    op.add_column('benches', sa.Column('organization_id', sa.String(), nullable=True))
    op.create_foreign_key('fk_benches_organization_id', 'benches', 'organizations', ['organization_id'], ['id'], ondelete='SET NULL')

    op.create_table(
        'subscriptions',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('organization_id', sa.String(), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('plan_id', sa.String(), sa.ForeignKey('plans.id'), nullable=False),
        sa.Column('status', sa.String(), nullable=False, server_default='trialing'),
        sa.Column('provider', sa.String(), nullable=True),
        sa.Column('provider_subscription_id', sa.String(), nullable=True),
        sa.Column('trial_ends_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('current_period_ends_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.UniqueConstraint('organization_id', name='uq_subscriptions_org'),
    )

    op.create_table(
        'site_domains',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('site_id', sa.String(), sa.ForeignKey('sites.id', ondelete='CASCADE'), nullable=False),
        sa.Column('domain', sa.String(), nullable=False),
        sa.Column('verification_status', sa.String(), nullable=False, server_default='pending'),
        sa.Column('ssl_status', sa.String(), nullable=False, server_default='provisioning'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.UniqueConstraint('domain', name='uq_site_domains_domain'),
    )
    op.create_table(
        'site_backups',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('site_id', sa.String(), sa.ForeignKey('sites.id', ondelete='CASCADE'), nullable=False),
        sa.Column('status', sa.String(), nullable=False, server_default='completed'),
        sa.Column('storage_ref', sa.String(), nullable=False),
        sa.Column('created_by_user_id', sa.String(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
    )


def downgrade() -> None:
    op.drop_table('site_backups')
    op.drop_table('site_domains')
    op.drop_table('subscriptions')
    op.drop_constraint('fk_benches_organization_id', 'benches', type_='foreignkey')
    op.drop_column('benches', 'organization_id')
    op.drop_constraint('fk_users_default_org_id', 'users', type_='foreignkey')
    op.drop_column('users', 'default_org_id')
    op.drop_table('organization_members')
    op.drop_table('organizations')
