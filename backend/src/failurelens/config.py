from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

if TYPE_CHECKING:
    from .providers import ProviderConfig


ProviderConfigurationStatus = Literal["disabled", "invalid_configuration", "ready"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="FAILURELENS_", env_file=".env", extra="ignore"
    )

    database_url: str = "sqlite+pysqlite:///./failurelens.db"
    database_pool_size: int = Field(default=10, ge=1, le=50)
    database_max_overflow: int = Field(default=10, ge=0, le=50)
    telemetry_export_enabled: bool = False
    telemetry_endpoint: str | None = None
    artifact_root: Path = Path("./artifacts")
    # Optional operator keyring; material is excluded from settings exports/repr.
    redaction_keyring: SecretStr | None = Field(default=None, exclude=True, repr=False)
    redaction_active_key_ref: str | None = None
    # Operator-only optional settings stay raw until explicitly requested. A typo
    # must disable provider work without preventing deterministic service startup.
    provider_enabled: str = "false"
    provider_id: str = ""
    provider_allowed_project_ids: str = ""
    provider_endpoint: str = ""
    provider_proxy: str = ""
    provider_model: str = ""
    provider_token: SecretStr | None = Field(default=None, exclude=True, repr=False)
    provider_timeout_seconds: str = "20"
    provider_max_attempts: str = "2"
    provider_max_context_bytes: str = "32000"
    provider_max_output_tokens: str = "1500"
    provider_max_response_bytes: str = "40000"
    provider_max_run_reserved_tokens: str = "20000"
    provider_max_run_requests: str = "5"
    provider_concurrency: str = "2"
    provider_min_interval_seconds: str = "1"
    provider_failure_threshold: str = "3"
    provider_cooldown_seconds: str = "60"
    provider_input_price_per_million: str = ""
    provider_output_price_per_million: str = ""
    provider_pricing_source: str = ""
    provider_pricing_date: str = ""
    provider_currency: str = ""
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
    evaluation_metrics_path: Path = Path(
        "../evaluation/reports/ledgerguard-component-v1-7405d923/metrics.json"
    )

    fullstack_evaluation_metrics_path: Path = Path(
        "../evaluation/reports/ledgerguard-fullstack-v1/metrics.json"
    )

    campaign_evaluation_metrics_path: Path = Path(
        "../evaluation/reports/diverse-v1/metrics.json"
    )

    benchmark_evaluation_metrics_path: Path = Path(
        "../evaluation/reports/benchmark-v1/metrics.json"
    )

    def provider_project_ids(self) -> frozenset[str]:
        """Parse at most 100 explicit project IDs; reject the entire invalid list.

        IDs are case-sensitive ASCII identifiers of at most 36 characters, as
        stored by the project table. Spaces around comma-separated entries are
        allowed, but empty entries, duplicates, wildcards and patterns are not.
        This method only parses scope; callers must also require a ready config.
        """
        raw = self.provider_allowed_project_ids
        if not raw or len(raw) > 7400:
            return frozenset()
        values = [value.strip() for value in raw.split(",")]
        if (
            len(values) > 100
            or len(set(values)) != len(values)
            or any(
                re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,35}", value) is None
                for value in values
            )
        ):
            return frozenset()
        return frozenset(values)

    def provider_configuration(
        self,
        *,
        require_credential: bool = True,
    ) -> tuple[ProviderConfig | None, ProviderConfigurationStatus]:
        """Return validated operator configuration or a fixed, non-secret status.

        Only the literal boolean values true/false (case-insensitive, with outer
        whitespace ignored) are supported. Disabled settings need no credential,
        scope or endpoint. No settings here are sourced from API request data.
        The API may validate metadata with require_credential=False; that result
        must never be used to construct a transport. Only the worker uses secrets.
        """
        enabled = self.provider_enabled.strip().casefold()
        if enabled == "false":
            return None, "disabled"
        if (
            enabled != "true"
            or re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,79}", self.provider_id) is None
            or not self.provider_project_ids()
        ):
            return None, "invalid_configuration"
        if require_credential and self.provider_token is None:
            return None, "invalid_configuration"
        token = (
            self.provider_token.get_secret_value()
            if require_credential and self.provider_token is not None
            else "metadata-only"
        )
        if not 1 <= len(token) <= 8192 or any(
            not 33 <= ord(character) <= 126 for character in token
        ):
            return None, "invalid_configuration"

        # Import lazily: the provider transport imports telemetry, which reads
        # these settings. Constructing configuration does not create a client.
        from .providers import ProviderConfig

        try:
            config = ProviderConfig(
                enabled=True,
                endpoint=self.provider_endpoint,
                proxy=self.provider_proxy or None,
                model=self.provider_model,
                token=token,
                timeout_seconds=float(self.provider_timeout_seconds),
                max_attempts=int(self.provider_max_attempts),
                max_context_bytes=int(self.provider_max_context_bytes),
                max_output_tokens=int(self.provider_max_output_tokens),
                max_response_bytes=int(self.provider_max_response_bytes),
                max_run_reserved_tokens=int(self.provider_max_run_reserved_tokens),
                max_run_requests=int(self.provider_max_run_requests),
                concurrency=int(self.provider_concurrency),
                min_interval_seconds=float(self.provider_min_interval_seconds),
                failure_threshold=int(self.provider_failure_threshold),
                cooldown_seconds=float(self.provider_cooldown_seconds),
                input_price_per_million=(
                    float(self.provider_input_price_per_million)
                    if self.provider_input_price_per_million
                    else None
                ),
                output_price_per_million=(
                    float(self.provider_output_price_per_million)
                    if self.provider_output_price_per_million
                    else None
                ),
                pricing_source=self.provider_pricing_source or None,
                pricing_date=self.provider_pricing_date or None,
                currency=self.provider_currency or None,
            )
            if config.proxy is not None:
                from .provider_proxy import ProxyPolicy

                destination = urlsplit(config.endpoint)
                hostname = destination.hostname
                if hostname is None or destination.netloc not in {
                    hostname,
                    f"{hostname}:443",
                }:
                    return None, "invalid_configuration"
                # The deployment gate permits one lowercase DNS host on 443.
                # Reuse its policy rather than accept an unusable configuration.
                ProxyPolicy(hostname)
        except (TypeError, ValueError, OverflowError):
            return None, "invalid_configuration"
        return config, "ready"

    def ensure_directories(self) -> None:
        self.artifact_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        (self.artifact_root / "incoming").mkdir(parents=True, exist_ok=True, mode=0o700)
        (self.artifact_root / "sources").mkdir(parents=True, exist_ok=True, mode=0o700)
        (self.artifact_root / "derivatives").mkdir(
            parents=True, exist_ok=True, mode=0o700
        )

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
