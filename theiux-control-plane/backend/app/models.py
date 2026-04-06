import uuid
from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column
from app.db import Base

def uid() -> str:
    return str(uuid.uuid4())

class User(Base):
    __tablename__ = 'users'
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    email: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String, nullable=False)
    role: Mapped[str] = mapped_column(String, nullable=False, default='owner')
    default_org_id: Mapped[str | None] = mapped_column(ForeignKey('organizations.id', ondelete='SET NULL'), nullable=True)
    created_at: Mapped[str] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Organization(Base):
    __tablename__ = 'organizations'

    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    name: Mapped[str] = mapped_column(String, nullable=False)
    slug: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    created_by_user_id: Mapped[str] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    created_at: Mapped[str] = mapped_column(DateTime(timezone=True), server_default=func.now())


class OrganizationMember(Base):
    __tablename__ = 'organization_members'
    __table_args__ = (UniqueConstraint('organization_id', 'user_id', name='uq_org_member'),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    organization_id: Mapped[str] = mapped_column(ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    role: Mapped[str] = mapped_column(String, nullable=False, default='viewer')
    created_at: Mapped[str] = mapped_column(DateTime(timezone=True), server_default=func.now())

class Plan(Base):
    __tablename__ = 'plans'
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    name: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    price_monthly: Mapped[int] = mapped_column(Integer, nullable=False)
    cpu_limit: Mapped[int] = mapped_column(Integer, nullable=False)
    ram_mb: Mapped[int] = mapped_column(Integer, nullable=False)
    bandwidth_gb: Mapped[int] = mapped_column(Integer, nullable=False)
    max_active_sites: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    max_deployments_per_day: Mapped[int] = mapped_column(Integer, nullable=False, default=20)
    max_concurrent_jobs: Mapped[int] = mapped_column(Integer, nullable=False, default=2)


class AppPreset(Base):
    """Curated deploy wizard templates (seeded; served by GET /v1/app-presets)."""

    __tablename__ = 'app_presets'

    slug: Mapped[str] = mapped_column(String(64), primary_key=True)
    label: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    git_repo_url: Mapped[str] = mapped_column(String(512), nullable=False)
    runtime: Mapped[str] = mapped_column(String(64), nullable=False)
    runtime_version: Mapped[str] = mapped_column(String(32), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[str] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Bench(Base):
    """Logical Frappe bench (one physical bench today; UI supports many rows per user)."""

    __tablename__ = 'benches'
    __table_args__ = (UniqueConstraint('user_id', 'slug', name='uq_benches_user_slug'),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    organization_id: Mapped[str | None] = mapped_column(ForeignKey('organizations.id', ondelete='SET NULL'), nullable=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    slug: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default='active')
    instance_ref: Mapped[str | None] = mapped_column(String, nullable=True)
    region: Mapped[str | None] = mapped_column(String, nullable=True)
    last_sync_at: Mapped[str | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_sync_status: Mapped[str | None] = mapped_column(String, nullable=True)
    last_sync_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(DateTime(timezone=True), server_default=func.now())

class BenchSourceApp(Base):
    """Git-backed app available on a bench (drives deploy-site / install flows)."""

    __tablename__ = 'bench_source_apps'
    __table_args__ = (UniqueConstraint('bench_id', 'name', name='uq_bench_source_apps_bench_name'),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    bench_id: Mapped[str] = mapped_column(ForeignKey('benches.id', ondelete='CASCADE'), nullable=False)
    plan_id: Mapped[str] = mapped_column(ForeignKey('plans.id'), nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    git_repo_url: Mapped[str] = mapped_column(String, nullable=False)
    git_branch: Mapped[str | None] = mapped_column(String, nullable=True)
    runtime: Mapped[str] = mapped_column(String, nullable=False)
    runtime_version: Mapped[str] = mapped_column(String, nullable=False)
    last_commit_sha: Mapped[str | None] = mapped_column(String, nullable=True)
    last_commit_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    synced_at: Mapped[str | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[str] = mapped_column(DateTime(timezone=True), server_default=func.now())

class Site(Base):
    __tablename__ = 'sites'
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    bench_id: Mapped[str] = mapped_column(ForeignKey('benches.id', ondelete='CASCADE'), nullable=False)
    domain: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default='provisioning')
    created_at: Mapped[str] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SiteDomain(Base):
    __tablename__ = 'site_domains'
    __table_args__ = (UniqueConstraint('domain', name='uq_site_domains_domain'),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    site_id: Mapped[str] = mapped_column(ForeignKey('sites.id', ondelete='CASCADE'), nullable=False)
    domain: Mapped[str] = mapped_column(String, nullable=False)
    verification_status: Mapped[str] = mapped_column(String, nullable=False, default='pending')
    ssl_status: Mapped[str] = mapped_column(String, nullable=False, default='provisioning')
    created_at: Mapped[str] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SiteBackup(Base):
    __tablename__ = 'site_backups'

    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    site_id: Mapped[str] = mapped_column(ForeignKey('sites.id', ondelete='CASCADE'), nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default='completed')
    storage_ref: Mapped[str] = mapped_column(String, nullable=False)
    created_by_user_id: Mapped[str] = mapped_column(ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    created_at: Mapped[str] = mapped_column(DateTime(timezone=True), server_default=func.now())

class SiteApp(Base):
    """Join: app installed (or pending) on a site."""

    __tablename__ = 'site_apps'
    __table_args__ = (UniqueConstraint('site_id', 'bench_source_app_id', name='uq_site_apps_site_app'),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    site_id: Mapped[str] = mapped_column(ForeignKey('sites.id', ondelete='CASCADE'), nullable=False)
    bench_source_app_id: Mapped[str] = mapped_column(
        ForeignKey('bench_source_apps.id', ondelete='CASCADE'), nullable=False
    )
    state: Mapped[str] = mapped_column(String, nullable=False, default='installed')
    installed_version: Mapped[str | None] = mapped_column(String, nullable=True)
    last_commit_sha: Mapped[str | None] = mapped_column(String, nullable=True)
    last_commit_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    synced_at: Mapped[str | None] = mapped_column(DateTime(timezone=True), nullable=True)

class Deployment(Base):
    __tablename__ = 'deployments'
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    bench_source_app_id: Mapped[str] = mapped_column(
        ForeignKey('bench_source_apps.id', ondelete='CASCADE'), nullable=False
    )
    operation: Mapped[str] = mapped_column(String, nullable=False, default='full_site')
    context: Mapped[dict] = mapped_column(JSON, nullable=False, insert_default=lambda: {})
    status: Mapped[str] = mapped_column(String, nullable=False, default='queued')
    last_error_type: Mapped[str | None] = mapped_column(String, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    stage_timestamps: Mapped[dict] = mapped_column(JSON, nullable=False, insert_default=lambda: {})
    created_at: Mapped[str] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[str] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

class Job(Base):
    __tablename__ = 'jobs'
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    deployment_id: Mapped[str] = mapped_column(ForeignKey('deployments.id', ondelete='CASCADE'), nullable=False)
    type: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default='queued')
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_retries: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    idempotency_key: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    logs: Mapped[str] = mapped_column(Text, nullable=False, default='')
    logs_json: Mapped[list[dict]] = mapped_column(JSON, nullable=False, default=list)
    last_error_type: Mapped[str | None] = mapped_column(String, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[str] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

class AuditLog(Base):
    __tablename__ = 'audit_logs'
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    action: Mapped[str] = mapped_column(String, nullable=False)
    resource_type: Mapped[str] = mapped_column(String, nullable=False)
    resource_id: Mapped[str | None] = mapped_column(String, nullable=True)
    meta: Mapped[dict | None] = mapped_column('metadata', JSON, nullable=True)
    created_at: Mapped[str] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RefreshToken(Base):
    __tablename__ = 'refresh_tokens'
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    token_hash: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    expires_at: Mapped[str] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[str | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ua_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[str] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Subscription(Base):
    __tablename__ = 'subscriptions'
    __table_args__ = (UniqueConstraint('organization_id', name='uq_subscriptions_org'),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    organization_id: Mapped[str] = mapped_column(ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False)
    plan_id: Mapped[str] = mapped_column(ForeignKey('plans.id'), nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default='trialing')
    provider: Mapped[str | None] = mapped_column(String, nullable=True)
    provider_subscription_id: Mapped[str | None] = mapped_column(String, nullable=True)
    trial_ends_at: Mapped[str | None] = mapped_column(DateTime(timezone=True), nullable=True)
    current_period_ends_at: Mapped[str | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[str] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[str] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
