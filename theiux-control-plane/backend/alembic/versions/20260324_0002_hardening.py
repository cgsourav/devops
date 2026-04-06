"""hardening auth, jobs, and logs"""
from alembic import op
import sqlalchemy as sa

revision = '20260324_0002'
down_revision = '20260324_0001'
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.add_column('deployments', sa.Column('last_error_type', sa.String(), nullable=True))
    op.add_column('jobs', sa.Column('attempt_count', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('jobs', sa.Column('max_retries', sa.Integer(), nullable=False, server_default='3'))
    op.add_column('jobs', sa.Column('idempotency_key', sa.String(), nullable=True))
    op.add_column('jobs', sa.Column('duration_ms', sa.Integer(), nullable=True))
    op.add_column('jobs', sa.Column('logs_json', sa.JSON(), nullable=False, server_default='[]'))
    op.add_column('jobs', sa.Column('last_error_type', sa.String(), nullable=True))
    op.create_unique_constraint('uq_jobs_idempotency_key', 'jobs', ['idempotency_key'])
    op.execute("UPDATE jobs SET idempotency_key = 'deploy:' || deployment_id WHERE idempotency_key IS NULL")
    op.alter_column('jobs', 'idempotency_key', nullable=False)
    op.create_table(
        'refresh_tokens',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('user_id', sa.String(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('token_hash', sa.String(), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
    )
    op.create_unique_constraint('uq_refresh_tokens_token_hash', 'refresh_tokens', ['token_hash'])

def downgrade() -> None:
    op.drop_constraint('uq_refresh_tokens_token_hash', 'refresh_tokens', type_='unique')
    op.drop_table('refresh_tokens')
    op.drop_constraint('uq_jobs_idempotency_key', 'jobs', type_='unique')
    op.drop_column('jobs', 'last_error_type')
    op.drop_column('jobs', 'logs_json')
    op.drop_column('jobs', 'duration_ms')
    op.drop_column('jobs', 'idempotency_key')
    op.drop_column('jobs', 'max_retries')
    op.drop_column('jobs', 'attempt_count')
    op.drop_column('deployments', 'last_error_type')
