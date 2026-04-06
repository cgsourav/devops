"""init schema"""
from alembic import op
import sqlalchemy as sa

revision = '20260324_0001'
down_revision = None
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.create_table('users', sa.Column('id', sa.String(), primary_key=True), sa.Column('email', sa.String(), nullable=False, unique=True), sa.Column('password_hash', sa.String(), nullable=False), sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False))
    op.create_table('plans', sa.Column('id', sa.String(), primary_key=True), sa.Column('name', sa.String(), nullable=False, unique=True), sa.Column('price_monthly', sa.Integer(), nullable=False), sa.Column('cpu_limit', sa.Integer(), nullable=False), sa.Column('ram_mb', sa.Integer(), nullable=False), sa.Column('bandwidth_gb', sa.Integer(), nullable=False))
    op.create_table('apps', sa.Column('id', sa.String(), primary_key=True), sa.Column('user_id', sa.String(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False), sa.Column('plan_id', sa.String(), sa.ForeignKey('plans.id'), nullable=False), sa.Column('name', sa.String(), nullable=False), sa.Column('git_repo_url', sa.String(), nullable=False), sa.Column('runtime', sa.String(), nullable=False), sa.Column('runtime_version', sa.String(), nullable=False), sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False))
    op.create_table('deployments', sa.Column('id', sa.String(), primary_key=True), sa.Column('app_id', sa.String(), sa.ForeignKey('apps.id', ondelete='CASCADE'), nullable=False), sa.Column('status', sa.String(), nullable=False), sa.Column('error_message', sa.Text(), nullable=True), sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False), sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False))
    op.create_table('sites', sa.Column('id', sa.String(), primary_key=True), sa.Column('app_id', sa.String(), sa.ForeignKey('apps.id', ondelete='CASCADE'), nullable=False), sa.Column('domain', sa.String(), nullable=False), sa.Column('status', sa.String(), nullable=False), sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False))
    op.create_table('jobs', sa.Column('id', sa.String(), primary_key=True), sa.Column('deployment_id', sa.String(), sa.ForeignKey('deployments.id', ondelete='CASCADE'), nullable=False), sa.Column('type', sa.String(), nullable=False), sa.Column('status', sa.String(), nullable=False), sa.Column('logs', sa.Text(), nullable=False, server_default=''), sa.Column('error_message', sa.Text(), nullable=True), sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False), sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False))

def downgrade() -> None:
    op.drop_table('jobs')
    op.drop_table('sites')
    op.drop_table('deployments')
    op.drop_table('apps')
    op.drop_table('plans')
    op.drop_table('users')
