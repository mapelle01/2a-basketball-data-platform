"""FASE 22.2 — Bulk Ingestion Runner tests (offline, mocks/fakes).

No FEB real, no API real, no production. Discovery, fetch y POST se simulan
con monkeypatch sobre los módulos reutilizados (`R.DM`, `R.IM`).
"""
from __future__ import annotations

import importlib.util
import json
import sys as _sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = json.loads((ROOT / "tests/ingestion/fixtures/boxscore_2486864.json").read_text())

_spec = importlib.util.spec_from_file_location(
    "ingest_round", ROOT / "scripts" / "feb" / "ingest_round.py"
)
R = importlib.util.module_from_spec(_spec)
_sys.modules[_spec.name] = R
_spec.loader.exec_module(R)

SEASON = "2025-2026"
ENV = {"FEB_TOKEN": "tok-" + "0" * 40, "FEB_TARGET_API": "http://api.test", "FEB_API_KEY": "key-" + "1" * 40}


def _refs(n, start=2486849):
    return [
        R.DM.MatchRef(
            external_id=start + i,
            round_number=1,
            scheduled_at="2025-10-04T00:00:00+01:00",
            home_team=f"HOME{i}",
            away_team=f"AWAY{i}",
            source_url=f"https://baloncestoenvivo.feb.es/Partido.aspx?p={start + i}",
        )
        for i in range(n)
    ]


@pytest.fixture
def ok_env(monkeypatch):
    for k, v in ENV.items():
        monkeypatch.setenv(k, v)


def _patch_discovery(monkeypatch, refs):
    monkeypatch.setattr(R.DM, "discover_matches", lambda season, round_, **kw: refs)


def _patch_fetch(monkeypatch, box=FIXTURE):
    monkeypatch.setattr(R.IM, "fetch_feb_boxscore", lambda match_id, token, base: box)


def _patch_ok_posts(monkeypatch, status=200):
    monkeypatch.setattr(
        R.IM, "post_command",
        lambda target, api_key, cmd: {"status": status, "body": {"ok": True}},
    )
    monkeypatch.setattr(
        R.IM, "post_stats_command",
        lambda target, api_key, cmd: {"status": status, "body": {"ok": True}},
    )


# --- 1. discovery devuelve N partidos
def test_discovery_returns_n_matches(monkeypatch, ok_env, capsys):
    calls = {}
    def fake(season, round_, **kw):
        calls["season"], calls["round"] = season, round_
        calls["group"] = kw.get("group")
        return _refs(3)
    monkeypatch.setattr(R.DM, "discover_matches", fake)
    _patch_fetch(monkeypatch)
    _patch_ok_posts(monkeypatch)

    rc = R.run_round(SEASON, 1)
    assert calls["season"] == SEASON and calls["round"] == 1
    assert calls["group"] == "ESTE"
    out = capsys.readouterr().out
    assert "discovered=3" in out
    assert rc == 0


# --- 2. todos los partidos se procesan
def test_all_matches_processed(monkeypatch, ok_env, capsys):
    _patch_discovery(monkeypatch, _refs(3))
    _patch_fetch(monkeypatch)
    _patch_ok_posts(monkeypatch)

    rc = R.run_round(SEASON, 1)
    out = capsys.readouterr().out
    assert rc == 0
    assert "match_ok=3" in out
    assert "stats_ok=3" in out
    assert "failed=0" in out
    assert out.count("OK") == 3


# --- 3. un fallo de un partido no impide procesar los siguientes
def test_one_failure_does_not_abort_round(monkeypatch, ok_env, capsys):
    _patch_discovery(monkeypatch, _refs(4))
    _patch_fetch(monkeypatch)

    def post(target, api_key, cmd):
        ext = cmd["payload"]["external_id"]
        if ext == "2486851":  # el tercero falla
            return {"status": 500, "body": {"error": "boom"}}
        return {"status": 200, "body": {"ok": True}}

    def post_stats(target, api_key, cmd):
        return {"status": 200, "body": {"ok": True}}

    monkeypatch.setattr(R.IM, "post_command", post)
    monkeypatch.setattr(R.IM, "post_stats_command", post_stats)

    rc = R.run_round(SEASON, 1)
    out = capsys.readouterr().out
    assert rc == 1
    assert "2486851 FAILED" in out
    assert "2486850 OK" in out
    assert "2486852 OK" in out
    assert "discovered=4" in out
    assert "match_ok=3" in out
    assert "failed=1" in out


# --- 4. se agregan correctamente los resultados (match OK pero stats falla)
def test_stats_failure_counts_failed_but_match_ok(monkeypatch, ok_env, capsys):
    _patch_discovery(monkeypatch, _refs(2))
    _patch_fetch(monkeypatch)
    monkeypatch.setattr(
        R.IM, "post_command",
        lambda target, api_key, cmd: {"status": 200, "body": {"ok": True}},
    )
    monkeypatch.setattr(
        R.IM, "post_stats_command",
        lambda target, api_key, cmd: {"status": 500, "body": {"error": "stats boom"}},
    )

    rc = R.run_round(SEASON, 1)
    out = capsys.readouterr().out
    assert rc == 1
    assert "match_ok=2" in out
    assert "stats_ok=0" in out
    assert "failed=2" in out


# --- 5. exit code correcto en éxito (0)
def test_exit_code_0_on_success(monkeypatch, ok_env):
    _patch_discovery(monkeypatch, _refs(2))
    _patch_fetch(monkeypatch)
    _patch_ok_posts(monkeypatch)
    assert R.run_round(SEASON, 1) == 0


# --- 6. exit code correcto con fallos (1)
def test_exit_code_1_on_failure(monkeypatch, ok_env):
    _patch_discovery(monkeypatch, _refs(2))
    _patch_fetch(monkeypatch)
    monkeypatch.setattr(
        R.IM, "post_command",
        lambda target, api_key, cmd: {"status": 503, "body": {}},
    )
    monkeypatch.setattr(
        R.IM, "post_stats_command",
        lambda target, api_key, cmd: {"status": 200, "body": {}},
    )
    assert R.run_round(SEASON, 1) == 1


# --- 7. dry-run no realiza POST
def test_dry_run_does_no_post(monkeypatch, capsys):
    _patch_discovery(monkeypatch, _refs(3))
    def boom(*a, **k):
        raise AssertionError("POST should not run in dry-run")
    monkeypatch.setattr(R.IM, "post_command", boom)
    monkeypatch.setattr(R.IM, "post_stats_command", boom)
    monkeypatch.setattr(R.IM, "fetch_feb_boxscore", boom)

    rc = R.run_round(SEASON, 1, dry_run=True)
    out = capsys.readouterr().out
    assert rc == 0
    assert "DRY RUN" in out
    assert "discovered=3" in out
    assert "POST disabled" in out
    assert "2486849" in out


# --- 8. los secretos no aparecen en la salida (ni en errores)
def test_secrets_never_in_output(monkeypatch, capsys):
    secret_token = "FEB_TOKEN_VALUE_XYZ_" + "a" * 40
    secret_key = "FEB_API_KEY_VALUE_XYZ_" + "b" * 40
    monkeypatch.setenv("FEB_TOKEN", secret_token)
    monkeypatch.setenv("FEB_TARGET_API", "http://api.test")
    monkeypatch.setenv("FEB_API_KEY", secret_key)
    _patch_discovery(monkeypatch, _refs(1))

    def fetch(match_id, token, base):
        raise RuntimeError(f"fetch failed with token={token}")
    monkeypatch.setattr(R.IM, "fetch_feb_boxscore", fetch)

    rc = R.run_round(SEASON, 1)
    out = capsys.readouterr().out
    err = capsys.readouterr().err
    assert rc == 1
    assert secret_token not in out
    assert secret_key not in out
    assert secret_token not in err
    assert "FAILED" in out
    # el token se sustituye por [redacted] en el error sanitizado
    assert "[redacted]" in out


# --- 9. el runner reutiliza la lógica existente (no duplica)
def test_runner_reuses_existing_logic():
    # No define funciones de ingestión/fetch/parse propias.
    for name in ("fetch_feb_boxscore", "parse_boxscore", "to_command", "to_stats_command",
                 "post_command", "post_stats_command", "fetch_calendar", "parse_calendar"):
        assert not hasattr(R, name), f"runner duplica {name}"
    # Reutiliza los módulos reales.
    assert R.DM.discover_matches.__module__ == "discover_matches"
    assert R.IM.parse_boxscore.__module__ == "ingest_match"
    assert R.IM.post_command.__module__ == "ingest_match"


# --- extras: exit codes de configuración/discovery (CLI run())
def test_run_cli_exit_2_bad_group(monkeypatch, capsys):
    monkeypatch.setattr(_sys, "argv", ["ingest_round.py", "--season", SEASON, "--round", "1", "--group", "SUR"])
    assert R.run() == 2
    assert "CONFIG_ERROR" in capsys.readouterr().err


def test_run_cli_exit_2_bad_season(monkeypatch, capsys):
    monkeypatch.setattr(_sys, "argv", ["ingest_round.py", "--season", "2024-2025", "--round", "1"])
    assert R.run() == 2
    assert "CONFIG_ERROR" in capsys.readouterr().err


def test_run_cli_exit_3_discovery_failed(monkeypatch, capsys):
    monkeypatch.setattr(_sys, "argv", ["ingest_round.py", "--season", SEASON, "--round", "1"])
    monkeypatch.setattr(R.DM, "discover_matches", lambda season, round_, **kw: (_ for _ in ()).throw(R.DM.SourceError("no source")))
    assert R.run() == 3
    assert "SOURCE_ERROR" in capsys.readouterr().err