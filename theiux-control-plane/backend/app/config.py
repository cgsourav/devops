from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', extra='ignore')
    database_url: str
    redis_url: str
    jwt_secret: str
    jwt_expires_minutes: int = 15
    refresh_token_expires_days: int = 14
    auth_rate_limit_per_minute: int = 20
    auth_rate_limit_burst: int = 8
    auth_secure_cookies: bool = False
    deploy_retry_rate_limit_per_minute: int = 3
    queue_max_depth: int = 0
    circuit_worker_lag_seconds: int = 0
    enable_refresh_token_binding: bool = False
    theiux_cli_path: str
    allowed_runtime_versions: str
    # Max wall-clock time for `theiux deploy-site` (SSM + bench); worker kills process on expiry.
    theiux_deploy_timeout_seconds: int = 3600
    # `theiux init` runs Terraform/AWS from the API process; can take many minutes.
    theiux_init_timeout_seconds: int = 3600
    # Optional: create first admin on API startup (set both; password ≥12 chars). Change via `python -m app.cli set-password`.
    bootstrap_admin_email: str | None = None
    bootstrap_admin_password: str | None = None

    @model_validator(mode='after')
    def bootstrap_admin_both_or_neither(self) -> 'Settings':
        e = (self.bootstrap_admin_email or '').strip()
        p = self.bootstrap_admin_password
        has_e = bool(e)
        has_p = bool(p)
        if has_e != has_p:
            raise ValueError(
                'Set both BOOTSTRAP_ADMIN_EMAIL and BOOTSTRAP_ADMIN_PASSWORD, or leave both unset.'
            )
        if has_p and len(p) < 12:
            raise ValueError('BOOTSTRAP_ADMIN_PASSWORD must be at least 12 characters when set.')
        self.bootstrap_admin_email = e or None
        return self


settings = Settings()
