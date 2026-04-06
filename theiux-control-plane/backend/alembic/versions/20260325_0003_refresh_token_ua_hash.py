"""refresh token optional UA binding hash"""
from alembic import op
import sqlalchemy as sa

revision = '20260325_0003'
down_revision = '20260324_0002'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('refresh_tokens', sa.Column('ua_hash', sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column('refresh_tokens', 'ua_hash')
