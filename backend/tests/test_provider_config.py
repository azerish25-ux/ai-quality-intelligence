from __future__ import annotations

import os
from dataclasses import fields
from pathlib import Path

import httpx
import pytest
from failurelens.config import Settings, get_settings
from failurelens.providers import ProviderConfig
from pydantic import SecretStr


@pytest.fixture(autouse=True)
def isolated_provider_environment(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)
    for name in os.environ:
        if name.startswith("FAILURELENS_PROVIDER_"):
            monkeypatch.delenv(name)


def configured_settings(monkeypatch: pytest.MonkeyPatch, **overrides: str) -> Settings:
    values = {
        "enabled": "true",
        "id": "operator-primary",
        "allowed_project_ids": "project-a,project-b",
        "endpoint": "https://provider.example/v1/chat/completions",
        "model": "test-fixture-not-a-model",
        "token": "fixture",
    }
    values.update(overrides)
    for name, value in values.items():
        monkeypatch.setenv(f"FAILURELENS_PROVIDER_{name.upper()}", value)
    return Settings()


def test_provider_is_disabled_without_any_operator_configuration() -> None:
    settings = Settings()
    assert settings.provider_configuration() == (None, "disabled")
    assert settings.provider_project_ids() == frozenset()
    assert settings.provider_token is None


def test_valid_provider_settings_cover_transport_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = configured_settings(monkeypatch)
    config, status = settings.provider_configuration()
    assert status == "ready"
    assert config is not None
    expected = ProviderConfig(
        endpoint="https://provider.example/v1/chat/completions",
        model="test-fixture-not-a-model",
        token="fixture",
        enabled=True,
    )
    assert config == expected
    assert settings.provider_project_ids() == frozenset({"project-a", "project-b"})
    assert all(
        f"provider_{field.name}" in Settings.model_fields for field in fields(config)
    )


def test_optional_configuration_errors_do_not_prevent_deterministic_startup(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("FAILURELENS_ARTIFACT_ROOT", str(tmp_path / "artifacts"))
    configured_settings(monkeypatch, max_attempts="not-an-integer")
    get_settings.cache_clear()
    try:
        settings = get_settings()
        settings.validate_security()
        assert settings.provider_configuration() == (None, "invalid_configuration")
        assert settings.database_pool_size == 10
        assert (settings.artifact_root / "derivatives").is_dir()
    finally:
        get_settings.cache_clear()


@pytest.mark.parametrize("enabled", ["false", "FALSE", " false "])
def test_disabled_provider_ignores_malformed_optional_values(
    monkeypatch: pytest.MonkeyPatch,
    enabled: str,
) -> None:
    settings = configured_settings(
        monkeypatch,
        enabled=enabled,
        allowed_project_ids="*",
        endpoint="not-an-endpoint",
        token="\n",
        max_attempts="not-an-integer",
    )
    assert settings.provider_configuration() == (None, "disabled")


@pytest.mark.parametrize("enabled", ["", "1", "0", "yes", "null", "tru", "{}"])
def test_malformed_enablement_fails_closed_without_settings_errors(
    monkeypatch: pytest.MonkeyPatch,
    enabled: str,
) -> None:
    settings = configured_settings(monkeypatch, enabled=enabled)
    assert settings.provider_configuration() == (None, "invalid_configuration")


@pytest.mark.parametrize("enabled", ["true", "TRUE", " true "])
def test_explicit_true_enablement_is_supported(
    monkeypatch: pytest.MonkeyPatch,
    enabled: str,
) -> None:
    settings = configured_settings(monkeypatch, enabled=enabled)
    assert settings.provider_configuration()[1] == "ready"


@pytest.mark.parametrize(
    "provider_id",
    ["", "Primary", "operator primary", "../primary", "primary\n", "*", "x" * 81],
)
def test_operator_identity_requires_an_explicit_stable_safe_identifier(
    monkeypatch: pytest.MonkeyPatch,
    provider_id: str,
) -> None:
    settings = configured_settings(monkeypatch, id=provider_id)
    assert settings.provider_configuration() == (None, "invalid_configuration")


@pytest.mark.parametrize(
    "project_ids",
    [
        "",
        " ",
        "*",
        "project-*",
        "project-a,*",
        "project-a,",
        ",project-a",
        "project-a,,project-b",
        "project-a,project-a",
        "project-a, project-a",
        "project-a;project-b",
        '["project-a"]',
        "project-a,../project-b",
        "project-a,project b",
        "project-a,prójèct-b",
        "x" * 37,
        ",".join(f"project-{number}" for number in range(101)),
        " " * 7401,
    ],
)
def test_malformed_allowlist_rejects_the_entire_scope(
    monkeypatch: pytest.MonkeyPatch,
    project_ids: str,
) -> None:
    settings = configured_settings(monkeypatch, allowed_project_ids=project_ids)
    assert settings.provider_project_ids() == frozenset()
    assert settings.provider_configuration() == (None, "invalid_configuration")


def test_allowlist_preserves_exact_case_sensitive_project_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = "00000000-0000-4000-8000-000000000001"
    settings = configured_settings(
        monkeypatch, allowed_project_ids=f" {project_id}, Project-A,project-a "
    )
    assert settings.provider_project_ids() == frozenset(
        {project_id, "Project-A", "project-a"}
    )
    assert settings.provider_configuration()[1] == "ready"


@pytest.mark.parametrize(
    "token",
    ["", " ", " fixture", "fixture ", "a\nb", "a\rb", "a\tb", "clé", "x" * 8193],
)
def test_malformed_credentials_do_not_raise_or_leak(
    monkeypatch: pytest.MonkeyPatch,
    token: str,
) -> None:
    settings = configured_settings(monkeypatch, token=token)
    assert settings.provider_configuration() == (None, "invalid_configuration")
    assert "provider_token" not in settings.model_dump()
    assert "provider_token" not in repr(settings)


def test_missing_credential_is_invalid_only_for_enabled_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configured_settings(monkeypatch)
    monkeypatch.delenv("FAILURELENS_PROVIDER_TOKEN")
    settings = Settings()
    assert settings.provider_configuration() == (None, "invalid_configuration")


def test_api_can_validate_metadata_without_worker_credential(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configured_settings(monkeypatch)
    monkeypatch.delenv("FAILURELENS_PROVIDER_TOKEN")
    settings = Settings()
    config, status = settings.provider_configuration(require_credential=False)
    assert status == "ready"
    assert config is not None
    assert config.token == "metadata-only"
    assert settings.provider_configuration() == (None, "invalid_configuration")


def test_metadata_configuration_does_not_use_credential(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = configured_settings(monkeypatch, token="a\nb")
    config, status = settings.provider_configuration(require_credential=False)
    assert status == "ready"
    assert config is not None
    assert config.token == "metadata-only"
    assert settings.provider_configuration() == (None, "invalid_configuration")


def test_metadata_configuration_still_requires_valid_operator_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = configured_settings(monkeypatch, allowed_project_ids="*")
    assert settings.provider_configuration(require_credential=False) == (
        None,
        "invalid_configuration",
    )


def test_explicit_egress_proxy_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = configured_settings(monkeypatch, proxy="http://provider-proxy:8080")
    config, status = settings.provider_configuration()
    assert status == "ready"
    assert config is not None
    assert config.proxy == "http://provider-proxy:8080"


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://provider.example/v1/chat/completions",
        "https://provider.example:443/v1/chat/completions",
    ],
)
def test_proxy_destination_matches_deployment_gate(
    monkeypatch: pytest.MonkeyPatch,
    endpoint: str,
) -> None:
    settings = configured_settings(
        monkeypatch, proxy="http://provider-proxy:8080", endpoint=endpoint
    )
    assert settings.provider_configuration()[1] == "ready"


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://provider.example:8443/v1/chat/completions",
        "https://Provider.Example/v1/chat/completions",
        "https://provider.example./v1/chat/completions",
        "https://provider_example.invalid/v1/chat/completions",
        "https://provider-example/v1/chat/completions",
        "https://127.0.0.1/v1/chat/completions",
        "https://[::1]/v1/chat/completions",
        "https://próvider.example/v1/chat/completions",
    ],
)
def test_proxy_destination_rejects_unsupported_authorities(
    monkeypatch: pytest.MonkeyPatch,
    endpoint: str,
) -> None:
    settings = configured_settings(
        monkeypatch, proxy="http://provider-proxy:8080", endpoint=endpoint
    )
    assert settings.provider_configuration() == (None, "invalid_configuration")


def test_direct_operator_endpoint_retains_custom_port_support(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = configured_settings(
        monkeypatch, endpoint="https://provider.example:8443/v1/chat/completions"
    )
    assert settings.provider_configuration()[1] == "ready"


@pytest.mark.parametrize(
    "proxy",
    [
        "https://provider-proxy:8080",
        "http://provider-proxy",
        "http://provider-proxy:0",
        "http://provider-proxy:-1",
        "http://provider-proxy:65536",
        "http://provider-proxy:8080/path",
        "http://provider-proxy:8080?configuration=fixture",
        "http://provider-proxy:8080#fragment",
        "http://operator@provider-proxy:8080",
        "http://@provider-proxy:8080",
        "http://provider-proxy\\other:8080",
        "http://provider-proxy\x7f:8080",
        "http://provider-proxy\n:8080",
    ],
)
def test_invalid_explicit_proxy_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    proxy: str,
) -> None:
    settings = configured_settings(monkeypatch, proxy=proxy)
    assert settings.provider_configuration() == (None, "invalid_configuration")


def test_configuration_never_constructs_http_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected_client(*args: object, **kwargs: object) -> None:
        raise AssertionError("configuration must not construct an HTTP client")

    monkeypatch.setattr(httpx, "Client", unexpected_client)
    settings = configured_settings(monkeypatch)
    assert settings.provider_configuration()[1] == "ready"
    assert settings.provider_configuration(require_credential=False)[1] == "ready"


def test_credential_can_come_from_operator_secret_directory(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    configured_settings(monkeypatch)
    monkeypatch.delenv("FAILURELENS_PROVIDER_TOKEN")
    (tmp_path / "FAILURELENS_PROVIDER_TOKEN").write_text("fixture", encoding="utf-8")
    monkeypatch.setitem(Settings.model_config, "secrets_dir", tmp_path)
    settings = Settings()
    config, status = settings.provider_configuration()
    assert status == "ready"
    assert config is not None
    assert config.token == "fixture"
    assert "provider_token" not in settings.model_dump()


def test_credential_is_hidden_in_settings_and_provider_representations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = "fixture-credential-for-redaction-check"
    settings = configured_settings(monkeypatch, token=token)
    assert isinstance(settings.provider_token, SecretStr)
    assert token not in repr(settings)
    assert token not in str(settings)
    assert token not in settings.model_dump_json()
    assert "provider_token" not in settings.model_dump()
    config, status = settings.provider_configuration()
    assert status == "ready"
    assert config is not None
    assert token not in repr(config)


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("timeout_seconds", "0"),
        ("timeout_seconds", "121"),
        ("timeout_seconds", "nan"),
        ("timeout_seconds", "inf"),
        ("timeout_seconds", "ten"),
        ("max_attempts", "0"),
        ("max_attempts", "4"),
        ("max_attempts", "2.0"),
        ("max_attempts", "true"),
        ("max_context_bytes", "1023"),
        ("max_context_bytes", "100001"),
        ("max_output_tokens", "0"),
        ("max_output_tokens", "8001"),
        ("max_response_bytes", "1023"),
        ("max_response_bytes", "200001"),
        ("max_run_reserved_tokens", "0"),
        ("max_run_reserved_tokens", "1000000001"),
        ("max_run_requests", "0"),
        ("max_run_requests", "101"),
        ("concurrency", "0"),
        ("concurrency", "17"),
        ("min_interval_seconds", "-1"),
        ("min_interval_seconds", "61"),
        ("min_interval_seconds", "nan"),
        ("failure_threshold", "0"),
        ("failure_threshold", "21"),
        ("cooldown_seconds", "-1"),
        ("cooldown_seconds", "3601"),
        ("cooldown_seconds", "nan"),
        ("input_price_per_million", "nan"),
        ("output_price_per_million", "infinity"),
        ("output_price_per_million", "unknown"),
    ],
)
def test_malformed_or_unbounded_numbers_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    value: str,
) -> None:
    settings = configured_settings(monkeypatch, **{name: value})
    assert settings.provider_configuration() == (None, "invalid_configuration")


def test_custom_bounded_limits_are_applied(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = configured_settings(
        monkeypatch,
        timeout_seconds="2.5",
        max_attempts="3",
        max_context_bytes="50000",
        max_output_tokens="2000",
        max_response_bytes="60000",
        max_run_reserved_tokens="30000",
        max_run_requests="8",
        concurrency="4",
        min_interval_seconds="0.5",
        failure_threshold="5",
        cooldown_seconds="120.5",
    )
    config, status = settings.provider_configuration()
    assert status == "ready"
    assert config == ProviderConfig(
        endpoint="https://provider.example/v1/chat/completions",
        model="test-fixture-not-a-model",
        token="fixture",
        enabled=True,
        timeout_seconds=2.5,
        max_attempts=3,
        max_context_bytes=50000,
        max_output_tokens=2000,
        max_response_bytes=60000,
        max_run_reserved_tokens=30000,
        max_run_requests=8,
        concurrency=4,
        min_interval_seconds=0.5,
        failure_threshold=5,
        cooldown_seconds=120.5,
    )


def test_complete_pricing_metadata_is_supported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = configured_settings(
        monkeypatch,
        input_price_per_million="0.5",
        output_price_per_million="1.5",
        pricing_source="Operator supplied synthetic fixture rates",
        pricing_date="2026-09-30",
        currency="USD",
    )
    config, status = settings.provider_configuration()
    assert status == "ready"
    assert config is not None
    assert config.input_price_per_million == 0.5
    assert config.output_price_per_million == 1.5
    assert config.pricing_source == "Operator supplied synthetic fixture rates"
    assert config.pricing_date == "2026-09-30"
    assert config.currency == "USD"


@pytest.mark.parametrize(
    "metadata",
    [
        {"input_price_per_million": "0.5"},
        {"output_price_per_million": "1.5"},
        {"pricing_source": "Operator supplied synthetic fixture rates"},
        {"pricing_date": "2026-09-30"},
        {"currency": "USD"},
    ],
)
def test_partial_pricing_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    metadata: dict[str, str],
) -> None:
    settings = configured_settings(monkeypatch, **metadata)
    assert settings.provider_configuration() == (None, "invalid_configuration")


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("endpoint", ""),
        ("endpoint", "http://provider.example/v1/chat/completions"),
        ("endpoint", "https://user:password@provider.example/v1/chat/completions"),
        ("endpoint", "https://provider.example/v1/chat/completions?token=fixture"),
        ("model", ""),
        ("model", "invalid model"),
        ("model", "model\n"),
        ("model", "x" * 201),
    ],
)
def test_transport_configuration_is_validated_without_a_client(
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    value: str,
) -> None:
    settings = configured_settings(monkeypatch, **{name: value})
    assert settings.provider_configuration() == (None, "invalid_configuration")
