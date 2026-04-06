"""Pydantic models for the public /v1 API contract."""

from datetime import datetime
from typing import Any
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, EmailStr, Field, computed_field, field_validator

# --- Auth ---


class RegisterIn(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={"example": {"email": "user@example.com", "password": "hunter2long"}}
    )

    email: EmailStr
    password: str = Field(min_length=8)


class RegisterOut(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {"id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890", "email": "user@example.com", "role": "owner"}
        }
    )

    id: str
    email: str
    role: str = 'owner'


class TokenOut(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
                "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
                "token_type": "bearer",
                "token_use": "access",
            }
        }
    )

    access_token: str
    refresh_token: str | None = None
    token_type: str = "bearer"
    token_use: str = Field(default="access", description="Semantic token role: access | refresh")


class RefreshIn(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={"example": {"refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."}}
    )

    refresh_token: str | None = None


class LogoutIn(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={"example": {"refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."}}
    )

    refresh_token: str | None = None


class LogoutOut(BaseModel):
    model_config = ConfigDict(json_schema_extra={"example": {"ok": True}})

    ok: bool = True


class UserMeOut(BaseModel):
    """Current user profile (for UI role checks)."""

    id: str
    email: str
    role: str
    default_org_id: str | None = None


class TheiuxInitIn(BaseModel):
    """Terraform variables for `theiux init` (passed as TF_VAR_*; matches theiux/terraform/variables.tf)."""

    aws_region: str = Field(..., min_length=1, max_length=64, description='e.g. us-east-1')
    repo_url: str = Field(..., min_length=1, max_length=2048, description='Git URL cloned on the EC2 instance')
    repo_ref: str | None = Field(default=None, max_length=256, description='Branch or tag (default in Terraform: main)')
    project_name: str | None = Field(default=None, max_length=64)
    environment: str | None = Field(default=None, max_length=64)
    instance_type: str | None = Field(default=None, max_length=64)
    root_volume_size_gb: int | None = Field(default=None, ge=8, le=2048)

    @field_validator('repo_url')
    @classmethod
    def repo_url_ok(cls, v: str) -> str:
        s = v.strip()
        if not s:
            raise ValueError('repo_url is empty')
        if s.startswith('git@'):
            if ':' not in s.split('@', 1)[-1]:
                raise ValueError('invalid git@ repository URL')
            return s
        parsed = urlparse(s)
        if parsed.scheme in {'https', 'http', 'ssh'}:
            if parsed.scheme in {'https', 'http'} and not parsed.netloc:
                raise ValueError('invalid repository URL')
            return s
        raise ValueError('repo_url must be https://, http://, ssh://, or git@…')


class TheiuxInitOut(BaseModel):
    """Result of running `theiux init` on the server (Terraform apply)."""

    ok: bool
    exit_code: int
    stdout: str = ''
    stderr: str = ''


class TheiuxInitStartOut(BaseModel):
    job_id: str
    status: str


class TheiuxInitStatusOut(BaseModel):
    job_id: str
    status: str
    started_at: str | None = None
    finished_at: str | None = None
    exit_code: int | None = None
    ok: bool | None = None
    logs: list[str] = Field(default_factory=list)
    stdout: str = ''
    stderr: str = ''


# --- Plans & apps ---


class PlanOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    price_monthly: int
    cpu_limit: int
    ram_mb: int
    bandwidth_gb: int
    max_active_sites: int = 3
    max_deployments_per_day: int = 20
    max_concurrent_jobs: int = 2


class AppCreateIn(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "name": "my-saas",
                "git_repo_url": "https://github.com/org/repo.git",
                "runtime": "python",
                "runtime_version": "3.11",
                "plan_id": "550e8400-e29b-41d4-a716-446655440000",
            }
        }
    )

    name: str
    git_repo_url: str
    runtime: str
    runtime_version: str
    plan_id: str
    git_branch: str | None = None
    bench_id: str | None = Field(default=None, description='Optional; defaults to your first bench')


class AppOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    bench_id: str
    plan_id: str
    name: str
    git_repo_url: str
    git_branch: str | None = None
    runtime: str
    runtime_version: str
    last_commit_sha: str | None = None
    last_commit_message: str | None = None
    synced_at: datetime | None = None
    created_at: datetime


class BenchCreateIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    slug: str | None = Field(default=None, max_length=64, description='URL slug; auto from name if omitted')
    instance_ref: str | None = None
    region: str | None = None


class BenchOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    name: str
    slug: str
    status: str
    instance_ref: str | None = None
    region: str | None = None
    last_sync_at: datetime | None = None
    last_sync_status: str | None = None
    last_sync_error: str | None = None
    created_at: datetime


class BenchSourceAppCreateIn(BaseModel):
    name: str
    git_repo_url: str
    runtime: str
    runtime_version: str
    plan_id: str
    git_branch: str | None = None


class BenchSourceAppOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    bench_id: str
    plan_id: str
    name: str
    git_repo_url: str
    git_branch: str | None = None
    runtime: str
    runtime_version: str
    last_commit_sha: str | None = None
    last_commit_message: str | None = None
    synced_at: datetime | None = None
    created_at: datetime


class AppPresetOut(BaseModel):
    id: str
    label: str
    description: str
    name: str
    git_repo_url: str
    runtime: str
    runtime_version: str


# --- Deployments ---


class DeploymentCreateIn(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={"example": {"app_id": "550e8400-e29b-41d4-a716-446655440000"}}
    )

    app_id: str


class DeploymentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    app_id: str = Field(description='Bench source app id (same id as POST /v1/apps and /source-apps)')
    operation: str = 'full_site'
    context: dict = Field(default_factory=dict)
    status: str
    last_error_type: str | None = None
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime
    stage_timestamps: dict[str, str | None] = Field(
        default_factory=dict,
        description='ISO timestamps when each pipeline stage was entered (queued, building, deploying, success, failed, …)',
    )
    suggested_actions: list[str] = Field(
        default_factory=list,
        description='Human-readable next steps derived from last_error_type when present',
    )


class DeploymentRetryOut(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "ok": True,
                "deployment_id": "660e8400-e29b-41d4-a716-446655440001",
                "job_id": "770e8400-e29b-41d4-a716-446655440002",
            }
        }
    )

    ok: bool
    deployment_id: str
    job_id: str


class DeploymentTransitionOut(BaseModel):
    model_config = ConfigDict(json_schema_extra={"example": {"id": "550e8400-e29b-41d4-a716-446655440000", "status": "building"}})

    id: str
    status: str


# --- Logs ---


class LogEntryOut(BaseModel):
    ts: str
    level: str = "info"
    message: str


class DeploymentLogsPlainOut(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "status": "failed",
                "error_message": "build failed",
                "last_error_type": "build_error",
                "lines": ["[theiux] building app image", "ERROR [build_error]: ..."],
            }
        }
    )

    status: str
    error_message: str | None = None
    last_error_type: str | None = Field(
        default=None,
        description="Same as deployment.last_error_type: build_error | migration_error | runtime_error",
    )
    lines: list[str]


class DeploymentLogsStructuredOut(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "status": "building",
                "total": 2,
                "offset": 0,
                "limit": 100,
                "entries": [
                    {"ts": "2026-03-25T12:00:00+00:00", "level": "info", "message": "[theiux] building"},
                    {"ts": "2026-03-25T12:00:01+00:00", "level": "error", "message": "ERROR [build_error]: ..."},
                ],
            }
        }
    )

    status: str
    total: int
    offset: int
    limit: int
    entries: list[dict[str, Any]]


# --- Sites ---


class SiteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    bench_id: str
    domain: str
    status: str
    created_at: datetime


class SiteAppOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    site_id: str
    bench_source_app_id: str
    app_name: str
    git_repo_url: str
    state: str
    installed_version: str | None = None
    last_commit_sha: str | None = None
    last_commit_message: str | None = None
    synced_at: datetime | None = None


class SiteDetailOut(BaseModel):
    site: SiteOut
    apps: list[SiteAppOut] = Field(default_factory=list)


class MigrateSuccessOut(BaseModel):
    model_config = ConfigDict(json_schema_extra={"example": {"ok": True}})

    ok: bool = True


class SiteDomainIn(BaseModel):
    domain: str = Field(..., min_length=3, max_length=255)


class SiteDomainOut(BaseModel):
    id: str
    site_id: str
    domain: str
    verification_status: str
    ssl_status: str
    created_at: datetime


class SiteBackupOut(BaseModel):
    id: str
    site_id: str
    status: str
    storage_ref: str
    created_at: datetime


class SiteBackupCreateOut(BaseModel):
    ok: bool = True
    backup: SiteBackupOut


class SiteRestoreIn(BaseModel):
    backup_id: str


class SiteRestoreOut(BaseModel):
    ok: bool = True
    site_id: str
    backup_id: str


# --- Audit ---


class AuditLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    action: str
    resource_type: str
    resource_id: str | None = None
    metadata: dict[str, Any] | None = Field(default=None, validation_alias='meta', serialization_alias='metadata')
    created_at: datetime


# --- System ---


class LimitsOut(BaseModel):
    limits: dict[str, int | None]
    usage: dict[str, int]
    remaining: dict[str, int | None]


class TeamMemberOut(BaseModel):
    user_id: str
    email: str
    role: str
    joined_at: datetime | None = None


class TeamOut(BaseModel):
    organization_id: str
    organization_name: str
    members: list[TeamMemberOut]


class TeamInviteIn(BaseModel):
    email: EmailStr
    role: str = Field(default='viewer')


class TeamInviteOut(BaseModel):
    ok: bool = True
    user_id: str
    role: str


class SubscriptionOut(BaseModel):
    id: str | None = None
    organization_id: str | None = None
    plan_id: str | None = None
    status: str
    provider: str | None = None
    trial_ends_at: datetime | None = None
    current_period_ends_at: datetime | None = None


class SubscriptionSelectPlanIn(BaseModel):
    plan_id: str


class SubscriptionSelectPlanOut(BaseModel):
    ok: bool = True
    subscription: SubscriptionOut


class WorkersStatusOut(BaseModel):
    last_heartbeat_unix: float | None = None
    heartbeat_age_seconds: float | None = None
    queue_depth: int
    started_jobs: int | None = None

    @computed_field
    @property
    def active_jobs(self) -> int | None:
        return self.started_jobs


class MetricsExportOut(BaseModel):
    requests_total: int
    jobs_total: int
    jobs_success: int
    jobs_failed: int
    avg_job_duration_ms: float
    error_categories: dict[str, int]
    queue_depth: int
    worker_last_heartbeat_unix: float | None = None
    worker_heartbeat_age_seconds: float | None = None
    started_jobs: int | None = None

    @computed_field
    @property
    def active_jobs(self) -> int | None:
        return self.started_jobs


class HealthOut(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "status": "ok",
                "metrics": {
                    "requests_total": 10,
                    "jobs_total": 2,
                    "jobs_success": 1,
                    "jobs_failed": 1,
                    "avg_job_duration_ms": 1234.5,
                    "error_categories": {"build_error": 1},
                },
            }
        }
    )

    status: str
    metrics: dict[str, Any]
