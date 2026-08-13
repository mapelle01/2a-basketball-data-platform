"""FASE 10 + FASE 11 — Architecture boundaries: the layered dependency rules hold.

  Domain         imports nothing internal
  Application    imports Domain only (handlers are SQLite-free)
  Infrastructure imports Application + Domain (+ the abstract api.CommandGateway
                 port, implemented by the composition root in wiring.py)
  API            imports Application + Domain + only the infra exceptions/logging
                 carve-out; never concrete repositories, sqlite3, or aggregates
"""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src" / "feb_score"
LAYERS = {"domain": SRC / "domain", "application": SRC / "application", "infrastructure": SRC / "infrastructure"}

# The API boundary may touch infrastructure ONLY through these two carve-outs.
API_ALLOWED_INFRA = {
    "feb_score.infrastructure.logging",
    "feb_score.infrastructure.persistence.errors",
}
# The composition root is the single module allowed to reach across into the
# abstract HTTP port that it implements.
INFRA_ALLOWED_API = {"feb_score.api.gateway"}


def _iter_modules(path: Path):
    for p in sorted(path.rglob("*.py")):
        if p.name == "__init__.py":
            continue
        yield p


def _module_package(p: Path) -> str:
    """feb_score package path a module file belongs to (e.g. api/main.py -> feb_score.api)."""
    rel = p.relative_to(SRC)
    parts = rel.parts[:-1]  # drop filename
    return "feb_score" + ("." + ".".join(parts) if parts else "")


def _resolved_internal_imports(p: Path) -> list:
    """Absolute feb_score.* modules imported by p (relative imports resolved)."""
    found = []
    pkg = _module_package(p)
    for node in ast.walk(ast.parse(p.read_text())):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("feb_score."):
                    found.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module is None:
                continue
            if node.level == 0:
                if node.module.startswith("feb_score."):
                    found.append(node.module)
            else:
                # climb (level-1) packages above our own package, then append module
                parts = pkg.split(".") if pkg else []
                if node.level > len(parts):
                    continue  # escapes the feb_score tree entirely
                base = parts[: len(parts) - (node.level - 1)]
                resolved = ".".join(base + ([node.module] if node.module else []))
                if resolved.startswith("feb_score."):
                    found.append(resolved)
    return found


def test_domain_imports_nothing_outside_its_package():
    for p in _iter_modules(LAYERS["domain"]):
        imports = _resolved_internal_imports(p)
        outside = [i for i in imports if not i.startswith("feb_score.domain")]
        assert outside == [], f"{p} imports outside the domain package: {outside}"


def test_application_never_imports_infrastructure():
    for p in _iter_modules(LAYERS["application"]):
        imports = _resolved_internal_imports(p)
        assert not any(i.startswith("feb_score.infrastructure") for i in imports), f"{p} imports infrastructure"
        assert "import sqlite3" not in p.read_text(), f"{p} imports sqlite3"


def test_application_never_imports_psycopg():
    for p in _iter_modules(LAYERS["application"]):
        assert "psycopg" not in p.read_text(), f"{p} references psycopg"


def test_domain_never_imports_database_drivers():
    for p in _iter_modules(LAYERS["domain"]):
        text = p.read_text()
        assert "psycopg" not in text, f"{p} references psycopg"
        assert "sqlite3" not in text, f"{p} references sqlite3"


def test_handlers_stay_sqlite_free():
    for p in _iter_modules(SRC / "application" / "use_cases"):
        assert "import sqlite3" not in p.read_text(), f"{p} imports sqlite3"


def test_infrastructure_imports_only_application_domain_self_and_gateway_port():
    for p in _iter_modules(LAYERS["infrastructure"]):
        imports = _resolved_internal_imports(p)
        for i in imports:
            assert (
                i.startswith("feb_score.application")
                or i.startswith("feb_score.domain")
                or i.startswith("feb_score.infrastructure")
                or i == "feb_score.api.gateway"
            ), f"{p} imports {i}"


def test_no_third_party_runtime_infrastructure():
    banned = ("sqlalchemy", "pydantic", "requests", "aiohttp", "httpx", "kafka", "redis", "boto3")
    for p in _iter_modules(LAYERS["infrastructure"]):
        text = p.read_text()
        for token in banned:
            assert token not in text, f"{p} references {token}"


# ---------------------------------------------------------------- FASE 11: API
def test_api_never_imports_concrete_infrastructure():
    for p in _iter_modules(SRC / "api"):
        imports = _resolved_internal_imports(p)
        for i in imports:
            assert not i.startswith("feb_score.infrastructure.persistence.repositories"), f"{p} imports {i}"
            assert not i.startswith("feb_score.infrastructure.persistence.connection"), f"{p} imports {i}"
            assert not i.startswith("feb_score.infrastructure.persistence.event_store"), f"{p} imports {i}"
            assert not i.startswith("feb_score.infrastructure.persistence.postgres"), f"{p} imports {i}"
            assert not i.startswith("feb_score.infrastructure.wiring"), f"{p} imports {i}"
            if i.startswith("feb_score.infrastructure"):
                assert i in API_ALLOWED_INFRA, f"{p} imports non-carve-out infra {i}"


def test_api_never_imports_psycopg():
    for p in _iter_modules(SRC / "api"):
        assert "psycopg" not in p.read_text(), f"{p} references psycopg"


def test_api_has_no_sqlite_and_no_domain_aggregates():
    for p in _iter_modules(SRC / "api"):
        text = p.read_text()
        assert "sqlite3" not in text, f"{p} references sqlite3"
        imports = _resolved_internal_imports(p)
        for i in imports:
            assert not i.startswith("feb_score.domain.match"), f"{p} imports aggregate {i}"
            assert not i.startswith("feb_score.domain.player"), f"{p} imports aggregate {i}"
            assert not i.startswith("feb_score.domain.team"), f"{p} imports aggregate {i}"
            assert not i.startswith("feb_score.domain.competition"), f"{p} imports aggregate {i}"


def test_api_imports_domain_only_via_errors():
    """The API may reference domain errors (for mapping) but no business logic.

    Carve-out: ``api/auth.py`` maps an authenticated principal to the domain
    ``Actor`` value object — the HTTP<->domain identity seam. It may import the
    Actor value object and nothing else from the domain.
    """
    for p in _iter_modules(SRC / "api"):
        imports = _resolved_internal_imports(p)
        for i in imports:
            if i.startswith("feb_score.domain"):
                if p.name == "auth.py":
                    assert i == "feb_score.domain.value_objects", (
                        f"{p} imports domain logic {i}"
                    )
                    continue
                assert i.startswith("feb_score.domain.errors") or i.startswith("feb_score.domain.common"), (
                    f"{p} imports domain logic {i}"
                )


def test_only_gateway_port_crosses_from_infrastructure():
    for p in _iter_modules(LAYERS["infrastructure"]):
        imports = _resolved_internal_imports(p)
        for i in imports:
            if i.startswith("feb_score.api"):
                assert i == "feb_score.api.gateway", f"{p} imports api module {i}"


def test_only_infrastructure_knows_postgres():
    """psycopg and the postgres package are allowed ONLY inside infrastructure."""
    for layer, path in LAYERS.items():
        if layer == "infrastructure":
            continue
        for p in _iter_modules(path):
            text = p.read_text()
            assert "psycopg" not in text, f"{p} references psycopg"
            assert "persistence.postgres" not in text, f"{p} references the postgres package"
    for p in _iter_modules(SRC / "api"):
        assert "persistence.postgres" not in p.read_text(), f"{p} references the postgres package"