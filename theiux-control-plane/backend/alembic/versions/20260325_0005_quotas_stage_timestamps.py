"""plan quotas and deployment stage_timestamps"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

revision = '20260325_0005'
down_revision = '20260325_0004'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('plans', sa.Column('max_active_sites', sa.Integer(), nullable=False, server_default='3'))
    op.add_column('plans', sa.Column('max_deployments_per_day', sa.Integer(), nullable=False, server_default='20'))
    op.add_column('plans', sa.Column('max_concurrent_jobs', sa.Integer(), nullable=False, server_default='2'))
    op.add_column(
        'deployments',
        sa.Column('stage_timestamps', sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
    )
    op.execute(
        text(
            """
            UPDATE plans SET max_active_sites = 1, max_deployments_per_day = 5, max_concurrent_jobs = 1 WHERE name = 'Free';
            UPDATE plans SET max_active_sites = 3, max_deployments_per_day = 20, max_concurrent_jobs = 2 WHERE name = 'Developer';
            UPDATE plans SET max_active_sites = 10, max_deployments_per_day = 100, max_concurrent_jobs = 5 WHERE name = 'Pro';
            """
        )
    )


def downgrade() -> None:
    op.drop_column('deployments', 'stage_timestamps')
    op.drop_column('plans', 'max_concurrent_jobs')
    op.drop_column('plans', 'max_deployments_per_day')
    op.drop_column('plans', 'max_active_sites')
