"""FASE 22.3 — Season Backfill Runner tests (offline, mocks/fakes).

No FEB real, no API real, no production. Discovery (fetch/parse del calendario)
y la ingesta por jornada (`ingest_round.run_round`) se simulan con monkeypatch.
"""
from __future__ import annotations

import importlib.util
import sys as _sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

_spec = importlib.util.spec_from_file_location(
    "ingest_season", ROOT / "scripts" / "feb" / "ingest_season.py"
)
S = importlib.util.module_from_spec(_spec)
_sys.modules[_spec.name] = S
_spec.loader.exec_module(S)

SEASON = "2025-2026"


def _refs(n, start=2486849, round_number=1):
    return [
        S.DM.MatchRef(
            external_id=start + i,
            round_number=round_number,
            scheduled_at="2025-10-04T00:00:00+01:00",
            home_team=f"HOME{i}",
            away_team=f"AWAY{i}",
            source_url=f"https://baloncestoenvivo.feb.es/Partido.aspx?p={start + i}",
        )
        for i in range(n)
    ]


def _calendar(rounds=(1, 2, 3), n=7):
    return {r: _refs(n, start=2486849 + 100 * (r - 1), round_number=r) for r in rounds}


def _patch_discovery(monkeypatch, by_round):
    def fake_parse(html):
        return by_round

    def fake_fetch(url):
        return "<html><h1>calendario</h1></html>"

    monkeypatch.setattr(S.DM, "parse_calendar", fake_parse)
    monkeypatch.setattr(S.DM, "fetch_calendar", fake_fetch)
    monkeypatch.setattr(
        S.DM, "_discovery_url", lambda season: f"https://feb.test/calendario?t={season}"
    )


def _patch_run_round(monkeypatch, outcome):
    """outcome: dict round -> ('ok'|'fail', n, failed) or an exception to raise."""
    def fake(season, round_, group=S.SUPPORTED_GROUP):
        spec = outcome.get(round_)
        if isinstance(spec, Exception):
            raise spec
        status, n, failed = spec
        ok = n - failed
        print(f"discovered={n}")
        print(f"match_ok={ok}")
        print(f"stats_ok={ok}")
        print(f"failed={failed}")
        if failed:
            print(f"1111111 FAILED boom-{round_}")
        return 1 if failed else 0

    monkeypatch.setattr(S.IR, "run_round", fake)


# --- 1. procesa varias jornadas
def test_processes_multiple_rounds(monkeypatch, capsys):
    _patch_discovery(monkeypatch, _calendar())
    _patch_run_round(monkeypatch, {1: ("ok", 7, 0), 2: ("ok", 7, 0), 3: ("ok", 7, 0)})

    rc = S.run_season(SEASON)
    out = capsys.readouterr().out
    assert rc == 0
    assert "rounds_discovered=3" in out
    assert "rounds_processed=3" in out
    assert "matches_discovered=21" in out
    assert "round=1  discovered=7" in out
    assert "round=2  discovered=7" in out
    assert "round=3  discovered=7" in out
    assert "STATUS: PASS" in out


# --- 2. respeta round-from
def test_respects_round_from(monkeypatch, capsys):
    _patch_discovery(monkeypatch, _calendar())
    _patch_run_round(monkeypatch, {2: ("ok", 7, 0), 3: ("ok", 7, 0)})

    rc = S.run_season(SEASON, round_from=2)
    out = capsys.readouterr().out
    assert rc == 0
    assert "rounds_discovered=2" in out
    assert "round=1" not in out
    assert "round=2" in out and "round=3" in out
    assert "matches_discovered=14" in out


# --- 3. respeta round-to
def test_respects_round_to(monkeypatch, capsys):
    _patch_discovery(monkeypatch, _calendar())
    _patch_run_round(monkeypatch, {1: ("ok", 7, 0), 2: ("ok", 7, 0)})

    rc = S.run_season(SEASON, round_to=2)
    out = capsys.readouterr().out
    assert rc == 0
    assert "rounds_discovered=2" in out
    assert "round=3" not in out
    assert "matches_discovered=14" in out


# --- 4. agrega correctamente los resultados
def test_aggregates_results(monkeypatch, capsys):
    _patch_discovery(monkeypatch, _calendar())
    _patch_run_round(monkeypatch, {1: ("ok", 7, 0), 2: ("ok", 7, 1), 3: ("ok", 7, 0)})

    rc = S.run_season(SEASON)
    out = capsys.readouterr().out
    assert rc == 1
    assert "matches_discovered=21" in out
    assert "matches_ok=20" in out
    assert "stats_ok=20" in out
    assert "failed=1" in out
    assert "STATUS: PARTIAL" in out


# --- 5. continúa después de una jornada parcialmente fallida
def test_continues_after_failed_round(monkeypatch, capsys):
    _patch_discovery(monkeypatch, _calendar())
    _patch_run_round(monkeypatch, {1: ("ok", 7, 0), 2: ("fail", 7, 2), 3: ("ok", 7, 0)})

    rc = S.run_season(SEASON)
    out = capsys.readouterr().out
    assert rc == 1
    assert "round=2  discovered=7  match_ok=5  stats_ok=5  failed=2" in out
    assert "round=3  discovered=7" in out  # la jornada 3 sigue procesándose
    assert "rounds_processed=3" in out
    assert "failed=2" in out


# --- 6. dry-run no hace POST
def test_dry_run_no_post(monkeypatch, capsys):
    _patch_discovery(monkeypatch, _calendar())

    def boom(*a, **k):
        raise AssertionError("run_round/POST should not run in dry-run")
    monkeypatch.setattr(S.IR, "run_round", boom)

    rc = S.run_season(SEASON, dry_run=True)
    out = capsys.readouterr().out
    assert rc == 0
    assert "DRY_RUN" in out
    assert "POST disabled" in out
    assert "rounds=3" in out
    assert "matches=21" in out


# --- 7. calcula correctamente los totales (matches_discovered por jornada)
def test_calculates_totals(monkeypatch, capsys):
    _patch_discovery(monkeypatch, {1: _refs(5, round_number=1), 2: _refs(7, start=2490000, round_number=2)})
    _patch_run_round(monkeypatch, {1: ("ok", 5, 0), 2: ("ok", 7, 0)})

    rc = S.run_season(SEASON)
    out = capsys.readouterr().out
    assert rc == 0
    assert "matches_discovered=12" in out
    assert "matches_ok=12" in out
    assert "stats_ok=12" in out
    assert "failed=0" in out


# --- 8. devuelve exit code correcto
def test_exit_code_success(monkeypatch):
    _patch_discovery(monkeypatch, _calendar())
    _patch_run_round(monkeypatch, {1: ("ok", 7, 0), 2: ("ok", 7, 0)})
    assert S.run_season(SEASON, round_to=2) == 0


def test_exit_code_failure(monkeypatch):
    _patch_discovery(monkeypatch, _calendar())
    _patch_run_round(monkeypatch, {1: ("ok", 7, 1), 2: ("ok", 7, 0)})
    assert S.run_season(SEASON, round_to=2) == 1


# --- 9. no imprime secretos (ni en excepciones de jornada)
def test_secrets_never_in_output(monkeypatch, capsys):
    secret_token = "SECRET_TOKEN_ZZZ_" + "c" * 40
    secret_key = "SECRET_APIKEY_ZZZ_" + "d" * 40
    monkeypatch.setenv("FEB_TOKEN", secret_token)
    monkeypatch.setenv("FEB_API_KEY", secret_key)
    _patch_discovery(monkeypatch, _calendar())
    _patch_run_round(monkeypatch, {
        1: RuntimeError(f"fetch boom token={secret_token} key={secret_key}"),
        2: ("ok", 7, 0),
    })

    rc = S.run_season(SEASON, round_to=2)
    out = capsys.readouterr().out
    assert rc == 1
    assert secret_token not in out
    assert secret_key not in out
    assert "ROUND 1 EXCEPTION" in out
    assert "[redacted]" in out
    assert "round=2  discovered=7" in out  # continúa


# --- extras: CLI exit codes y aislamiento de jornada con excepción
def test_cli_exit_2_bad_group(monkeypatch, capsys):
    monkeypatch.setattr(_sys, "argv", ["ingest_season.py", "--season", SEASON, "--group", "SUR"])
    assert S.run() == 2
    assert "CONFIG_ERROR" in capsys.readouterr().err


def test_cli_exit_2_bad_range(monkeypatch, capsys):
    monkeypatch.setattr(_sys, "argv", ["ingest_season.py", "--season", SEASON, "--round-from", "5", "--round-to", "3"])
    assert S.run() == 2
    assert "CONFIG_ERROR" in capsys.readouterr().err


def test_cli_exit_2_round_from_zero(monkeypatch, capsys):
    monkeypatch.setattr(_sys, "argv", ["ingest_season.py", "--season", SEASON, "--round-from", "0"])
    assert S.run() == 2
    assert "CONFIG_ERROR" in capsys.readouterr().err


def test_cli_exit_3_discovery_failed(monkeypatch, capsys):
    monkeypatch.setattr(_sys, "argv", ["ingest_season.py", "--season", SEASON])
    monkeypatch.setattr(S.DM, "fetch_calendar", lambda url: (_ for _ in ()).throw(S.DM.SourceError("calendar down")))
    assert S.run() == 3
    assert "SOURCE_ERROR" in capsys.readouterr().err


# --- reutiliza la lógica existente (no duplica ingestión)
def test_runner_reuses_existing_logic():
    for name in ("fetch_feb_boxscore", "parse_boxscore", "to_command", "to_stats_command",
                 "post_command", "post_stats_command", "fetch_calendar", "parse_calendar"):
        assert not hasattr(S, name), f"season runner duplica {name}"
    # Delega la ingesta por jornada en ingest_round.run_round
    assert S.IR.run_round.__module__ == "ingest_round"
    # Enumeración de jornadas vía discover_matches.fetch_calendar/parse_calendar
    assert S.DM.parse_calendar.__module__ == "discover_matches"