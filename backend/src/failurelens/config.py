from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="FAILURELENS_", env_file=".env", extra="ignore")

    database_url: str = "sqlite+pysqlite:///./failurelens.db"
    artifact_root: Path = Path("./artifacts")
    demo_mode: bool = True
    session_cookie_name: str = "failurelens_session"
    session_ttl_hours: int = Field(default=12, ge=1, le=24 * 30)
    session_cookie_secure: bool = False
    bootstrap_admin_username: str | None = None
    bootstrap_admin_password: str | None = None
    bootstrap_admin_display_name: str = "FailureLens Administrator"
    # Deprecated global credential retained only so production startup can
    # reject it explicitly instead of silently granting cross-project access.
    ingestion_token: str | None = None
    max_file_bytes: int = Field(default=50 * 1024 * 1024, ge=1024)
    max_bundle_bytes: int = Field(default=250 * 1024 * 1024, ge=1024)
    max_archive_entries: int = Field(default=2000, ge=1)
    max_expanded_bytes: int = Field(default=500 * 1024 * 1024, ge=1024)
    max_compression_ratio: int = Field(default=100, ge=1)
    max_image_pixels: int = Field(default=25_000_000, ge=1)
    analysis_text_budget: int = Field(default=40_000, ge=1000)
    job_lease_seconds: int = Field(default=60, ge=5)
    job_max_attempts: int = Field(default=3, ge=1, le=20)
    evaluation_metrics_path: Path = Path("../evaluation/reports/ledgerguard-component-v1-7405d923/metrics.json")

    fullstack_evaluation_metrics_path: Path = Path("../evaluation/reports/ledgerguard-fullstack-v1/metrics.json")

    def ensure_directories(self) -> None:
        self.artifact_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        (self.artifact_root / "incoming").mkdir(parents=True, exist_ok=True, mode=0o700)
        (self.artifact_root / "sources").mkdir(parents=True, exist_ok=True, mode=0o700)
        (self.artifact_root / "derivatives").mkdir(parents=True, exist_ok=True, mode=0o700)

    def validate_security(self) -> None:
        if self.demo_mode:
            return
        if self.ingestion_token:
            raise RuntimeError(
                "FAILURELENS_INGESTION_TOKEN is a deprecated global credential; create a project-scoped ingestion token"
            )
        username = (self.bootstrap_admin_username or "").strip()
        password = self.bootstrap_admin_password or ""
        if not username:
            raise RuntimeError(
                "production mode requires FAILURELENS_BOOTSTRAP_ADMIN_USERNAME"
            )
        if len(password) < 14:
            raise RuntimeError(
                "production mode requires a bootstrap administrator password of at least 14 characters"
            )
        if password.lower() in {
            "changemechangeme",
            "passwordpassword",
            "failurelensadmin",
            "administrator123",
        }:
            raise RuntimeError("bootstrap administrator password is unsafe")
        if not self.session_cookie_secure:
            raise RuntimeError(
                "production mode requires FAILURELENS_SESSION_COOKIE_SECURE=true"
            )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_directories()
    return settings
