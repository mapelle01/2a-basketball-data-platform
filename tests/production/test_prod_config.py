"""FASE 13 — Configuration validation: fail fast at boot, never in production."""

import os

import pytest

from feb_score.infrastructure.config import (
    ConfigurationError,
    Settings,
    settings_from_env,
)


def test_development_defaults_validate():
    Settings().validate()  # no error


def test_invalid_environment_rejected():
    with pytest.raises(ConfigurationError, match="FEB_SCORE_ENV"):
        Settings(env="staging").validate()


def test_invalid_log_level_rejected():
    with pytest.raises(ConfigurationError, match="FEB_SCORE_LOG_LEVEL"):
        Settings(log_level="verbose").validate()


def test_non_positive_timeouts_rejected():
    with pytest.raises(ConfigurationError, match="timeouts"):
        Settings(pg_connect_timeout_ms=0).validate()
    with pytest.raises(ConfigurationError, match="timeouts"):
        Settings(pg_statement_timeout_ms=-1).validate()


def test_non_positive_rate_limit_rejected():
    with pytest.raises(ConfigurationError, match="RATE_LIMIT_PER_MINUTE"):
        Settings(rate_limit_per_minute=0).validate()


def test_invalid_integer_env_vars_fail_fast_with_name(monkeypatch):
    """FASE 15 §4: a non-integer value for an integer env var fails fast at
    config load, naming the variable — never a bare Python ValueError."""
    monkeypatch.setenv("FEB_SCORE_RATE_LIMIT_PER_MINUTE", "abc")
    with pytest.raises(ConfigurationError, match="FEB_SCORE_RATE_LIMIT_PER_MINUTE"):
        settings_from_env()
    monkeypatch.setenv("FEB_SCORE_RATE_LIMIT_PER_MINUTE", "120")

    monkeypatch.setenv("FEB_SCORE_PG_CONNECT_TIMEOUT", "not-a-number")
    with pytest.raises(ConfigurationError, match="FEB_SCORE_PG_CONNECT_TIMEOUT"):
        settings_from_env()
    monkeypatch.setenv("FEB_SCORE_PG_CONNECT_TIMEOUT", "5000")

    monkeypatch.setenv("FEB_SCORE_BUSY_TIMEOUT", "")
    assert settings_from_env().busy_timeout_ms == 5000  # empty -> default


def test_module_import_survives_malformed_integer_env():
    """FASE 15 §4 regression guard: malformed integer env vars must NEVER crash
    at import time (eager int() in module/class defaults) — the error belongs at
    boot, as a named ConfigurationError."""
    import subprocess
    import sys

    env = os.environ.copy()
    env["PYTHONPATH"] = os.path.join(os.path.dirname(__file__), "..", "..", "src")
    env["FEB_SCORE_RATE_LIMIT_PER_MINUTE"] = "abc"
    env["FEB_SCORE_PORT"] = "abc"
    r = subprocess.run(
        [sys.executable, "-c", "import feb_score.server"],
        capture_output=True, text=True, env=env, timeout=60,
    )
    assert r.returncode == 0, (r.stdout + r.stderr) or "import crashed"

    # the malformed values must fail fast with a NAMED error at boot, not at import
    env["FEB_SCORE_ENV"] = "development"
    env.pop("FEB_SCORE_PORT")
    r = subprocess.run(
        [sys.executable, "-c", "import feb_score.server; feb_score.server.main()"],
        capture_output=True, text=True, env=env, timeout=60,
    )
    txt = (r.stdout or "") + (r.stderr or "")
    assert r.returncode != 0, "expected boot to fail"
    assert "FEB_SCORE_RATE_LIMIT_PER_MINUTE" in txt, txt

    env.pop("FEB_SCORE_RATE_LIMIT_PER_MINUTE")
    env["FEB_SCORE_PORT"] = "abc"
    r = subprocess.run(
        [sys.executable, "-c", "import feb_score.server; feb_score.server.main()"],
        capture_output=True, text=True, env=env, timeout=60,
    )
    txt = (r.stdout or "") + (r.stderr or "")
    assert r.returncode != 0, "expected boot to fail"
    assert "FEB_SCORE_PORT" in txt, txt


def test_production_requires_database_url():
    with pytest.raises(ConfigurationError, match="FEB_SCORE_DATABASE_URL"):
        Settings(env="production", api_keys="k=id:admin").validate()


def test_production_requires_api_keys():
    with pytest.raises(ConfigurationError, match="FEB_SCORE_API_KEYS"):
        Settings(env="production", database_url="postgresql://user@host/db").validate()


def test_production_valid_when_fully_configured():
    Settings(
        env="production",
        database_url="postgresql://user@host/db",
        api_keys="k=id:admin",
    ).validate()  # no error


def test_settings_from_env_reads_documented_variables(monkeypatch):
    monkeypatch.setenv("FEB_SCORE_ENV", "production")
    monkeypatch.setenv("FEB_SCORE_DATABASE_URL", "postgresql://u:p@h/db")
    monkeypatch.setenv("FEB_SCORE_API_KEYS", "k=id:admin")
    monkeypatch.setenv("FEB_SCORE_RATE_LIMIT", "false")
    s = settings_from_env()
    assert s.env == "production"
    assert s.database_url == "postgresql://u:p@h/db"
    assert s.api_keys == "k=id:admin"
    assert s.rate_limit_enabled is False
    s.validate()


def test_secrets_never_printed_by_validate(monkeypatch):
    """Config errors must not embed the DSN password or API keys."""
    monkeypatch.setenv("FEB_SCORE_DATABASE_URL", "postgresql://user:S3CR3T@host/db")
    monkeypatch.setenv("FEB_SCORE_API_KEYS", "secret-key=id:admin")
    try:
        settings_from_env().validate()
    except ConfigurationError as exc:
        assert "S3CR3T" not in str(exc)
        assert "secret-key" not in str(exc)


def test_api_key_parsing_errors_surface_at_boot():
    from feb_score.api.auth import ApiKeyAuthenticationProvider

    with pytest.raises(ValueError, match="expected key=id:role"):
        ApiKeyAuthenticationProvider.from_env("not-an-entry")
    with pytest.raises(ValueError, match="invalid API key role"):
        ApiKeyAuthenticationProvider.from_env("k=id:superuser")
    with pytest.raises(ValueError, match="empty API key"):
        ApiKeyAuthenticationProvider.from_env("=id:admin")

    provider = ApiKeyAuthenticationProvider.from_env("k=id:admin;e=ed-1:editor")
    admin = provider.authenticate(_request_with("Authorization: Bearer k"))
    assert admin is not None and admin.id == "id" and admin.role == "admin"
    editor = provider.authenticate(_request_with("X-API-Key: e"))
    assert editor is not None and editor.id == "ed-1" and editor.role == "editor"
    assert provider.authenticate(_request_with("Bearer bogus")) is None


def _request_with(header: str):
    from starlette.requests import Request

    name, _, value = header.partition(":")
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/v1/commands/x",
        "headers": [(name.strip().lower().encode(), value.strip().encode())],
        "query_string": b"",
    }
    return Request(scope)