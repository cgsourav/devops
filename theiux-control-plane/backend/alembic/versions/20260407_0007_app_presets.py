"""App presets catalog (DB-backed quick-starts for deploy wizard)."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = '20260407_0007'
down_revision = '20260406_0006'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'app_presets',
        sa.Column('slug', sa.String(64), primary_key=True),
        sa.Column('label', sa.String(256), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('name', sa.String(128), nullable=False),
        sa.Column('git_repo_url', sa.String(512), nullable=False),
        sa.Column('runtime', sa.String(64), nullable=False),
        sa.Column('runtime_version', sa.String(32), nullable=False),
        sa.Column('sort_order', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
    )


def downgrade() -> None:
    op.drop_table('app_presets')
