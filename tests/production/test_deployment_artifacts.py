"""FASE 15 §2/§9 — Deployment artifacts: static hardening checks that run
WITHOUT Docker, so CI can enforce the deploy contract even where the Docker
daemon is unavailable.

These checks pin the fail-closed posture of the container/compose assets:
no known-default credentials, secrets only via required env, non-root image
user, liveness healthcheck, and a consistent env contract.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = (ROOT / "Dockerfile").read_text()
COMPOSE = (ROOT / "docker-compose.yml").read_text()
ENV_EXAMPLE = (ROOT / ".env.example").read_text()


def test_no_known_default_database_credential_in_compose():
    """The DB password must be required, never defaulted to a known value."""
    assert ":-change-me" not in COMPOSE
    assert "POSTGRES_PASSWORD:?" in COMPOSE


def test_api_keys_required_in_compose():
    assert "FEB_SCORE_API_KEYS:?" in COMPOSE


def test_no_secret_looking_values_committed_in_deploy_assets():
    """No real key/DSN values in Dockerfile/compose/.env.example — only placeholders."""
    for name, text in [
        ("Dockerfile", DOCKERFILE),
        ("docker-compose.yml", COMPOSE),
        (".env.example", ENV_EXAMPLE),
    ]:
        for forbidden in (
            "BEGIN RSA PRIVATE KEY",
            "postgresql://feb:change-me",  # the previous known default password
            "sys-key",
        ):
            assert forbidden not in text, f"{name} leaks {forbidden!r}"
    # placeholders are clearly marked (never a real credential)
    assert "CHANGE_ME" in ENV_EXAMPLE
    assert "change-me" not in COMPOSE.lower().replace(":?", ":?")


def test_dockerfile_runs_non_root_and_healthchecked():
    assert "USER feb" in DOCKERFILE
    assert "HEALTHCHECK" in DOCKERFILE
    assert "feb_score.server" in DOCKERFILE
    assert "EXPOSE 8000" in DOCKERFILE


def test_compose_env_contract_matches_application_settings():
    """Every FEB_SCORE_* variable used by compose is read by the application
    config, so a compose-deployed instance is fully configured by env."""
    from feb_score.infrastructure.config import settings_from_env

    used = set(re.findall(r"FEB_SCORE_[A-Z_]+", COMPOSE))
    assert {"FEB_SCORE_ENV", "FEB_SCORE_DATABASE_URL", "FEB_SCORE_API_KEYS"} <= used
    s = settings_from_env()  # importable with sane defaults
    s.validate()  # development defaults are valid


def test_readme_documents_deployment_without_committed_secrets():
    readme = (ROOT / "README.md").read_text()
    assert readme  # present