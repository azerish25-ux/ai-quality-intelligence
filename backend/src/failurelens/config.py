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
    ingestion_token: str | None = None
    max_file_bytes: int = Field(default=50 * 1024 * 1024, ge=1024)
    max_bundle_bytes: int = Field(default=250 * 1024 * 1024, ge=1024)
    max_archive_entries: int = Field(default=2000, ge=1)
    max_expanded_bytes: int = Field(default=500 * 1024 * 1024, ge=1024)
    analysis_text_budget: int = Field(default=40_000, ge=1000)
    job_lease_seconds: int = Field(default=60, ge=5)
    evaluation_metrics_path: Path = Path("../evaluation/reports/latest/metrics.json")

    def ensure_directories(self) -> None:
        self.artifact_root.mkdir(parents=True, exist_ok=True, mode=0o700)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_directories()
    return settings
