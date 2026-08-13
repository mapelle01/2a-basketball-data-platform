"""FASE 10 + FASE 11 — Dependency hygiene: runtime deps declared apart from dev
deps, and no test/dev-only imports leak into production code."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_runtime_requirements_declare_core_deps():
    req = (ROOT / "requirements.txt").read_text()
    for dep in ("jsonschema", "fastapi", "uvicorn", "psycopg"):
        assert any(line.strip().startswith(dep) for line in req.splitlines()), dep


def test_dev_requirements_declare_test_deps():
    req = (ROOT / "requirements-dev.txt").read_text()
    # FASE 13: jsonschema is declared once, as a RUNTIME dependency
    # (requirements.txt); it is intentionally not duplicated here.
    for dep in ("pytest", "hypothesis", "httpx"):
        assert any(line.strip().startswith(dep) for line in req.splitlines()), dep
    lines = [line.strip() for line in req.splitlines() if line.strip()]
    assert not any(l.startswith("jsonschema") for l in lines), "jsonschema must not be duplicated in dev requirements"


def test_runtime_and_dev_requirements_are_separate_files():
    assert (ROOT / "requirements.txt").exists()
    assert (ROOT / "requirements-dev.txt").exists()


def test_no_pytest_imports_in_src():
    for path in (ROOT / "src").rglob("*.py"):
        assert "import pytest" not in path.read_text(), path


def test_no_external_services_in_imports():
    """No Kafka/Redis/HTTP-client/cloud SDK leaks into the codebase (the HTTP
    *server* deps fastapi/uvicorn are legitimate; outbound clients are not)."""
    banned = ("kafka", "redis", "requests", "aiohttp", "httpx", "boto3", "sqlalchemy")
    for path in (ROOT / "src").rglob("*.py"):
        text = path.read_text()
        for token in banned:
            assert f"import {token}" not in text, f"{path} imports {token}"