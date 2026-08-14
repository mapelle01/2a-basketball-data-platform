"""FASE 21.B2 — connector tests against the REAL FEB BoxScore fixture.

Offline only: reads tests/ingestion/fixtures/boxscore_2486864.json.
No FEB token, no API key, no network, no production POST in these tests.
"""
from __future__ import annotations

import importlib.util
import json
import sys as _sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = json.loads((ROOT / "tests/ingestion/fixtures/boxscore_2486864.json").read_text())

# Load connector module from arbitrary path (scripts/feb/ not on sys.path by default).
_spec = importlib.util.spec_from_file_location(
    "ingest_match", ROOT / "scripts" / "feb" / "ingest_match.py"
)
M = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(M)

SEASON = "2025-2026"
MATCH_ID = "2486864"


def _parsed():
    return M.parse_boxscore(FIXTURE, match_id=MATCH_ID, season_code=SEASON)


# --- 1. parse_boxscore con fixture real
def test_parse_returns_real_competition_and_compid():
    p = _parsed()
    assert p["competition"] == "SEGUNDA FEB"
    assert p["comp_id"] == "118"


# --- 2. external_id
def test_external_id_real_match_id():
    assert _parsed()["external_id"] == "2486864"


# --- 3. equipos
def test_teams_home_away_real_names_and_ids():
    p = _parsed()
    home, away = p["teams"]["home"], p["teams"]["away"]
    assert home["id"] == "979897"
    assert home["name"] == "BUENO ARENAS ALBACETE BASKET"
    assert away["id"] == "981281"
    assert away["name"] == "LOBE HUESCA LA MAGIA"


# --- 4. marcador final (HEADER.TEAM[].pts authoritative)
def test_final_score_80_88():
    p = _parsed()
    assert p["teams"]["home"]["score"] == 80
    assert p["teams"]["away"]["score"] == 88


# --- 5. parciales
def test_quarters_4_periods_correct():
    p = _parsed()
    q = p["quarters"]
    assert [(x["period"], x["home_score"], x["away_score"]) for x in q] == [
        (1, 15, 20),
        (2, 17, 30),
        (3, 22, 16),
        (4, 26, 22),
    ]


# --- 6. fecha normalizada
def test_scheduled_at_iso_with_b2_offset():
    p = _parsed()
    assert p["scheduling"]["scheduled_at"] == "2025-10-18T19:00:00+01:00"


# --- 7. REID (player real del fixture)
def test_reid_player_real_stats():
    p = _parsed()
    def by_name(players, needle):
        for pl in players:
            if pl["name"] == needle:
                return pl
        raise AssertionError(f"player {needle} not found")
    reid = by_name(p["stats"]["home"], "N. REID")
    assert reid["id"] == "2813013"
    assert reid["pts"] == 12
    assert reid["reb"] == 6
    assert reid["assist"] == 1
    assert reid["val"] == 14


def test_player_stats_keys_present():
    p = _parsed()
    required = {"id", "name", "no", "min", "pts", "reb", "assist", "val", "to", "bs",
                "st", "pf", "p1m", "p1a", "p1p", "p2m", "p2a", "p2p", "p3m", "p3a", "p3p"}
    player = p["stats"]["home"][0]
    assert required.issubset(set(player))


# --- 8. command_id determinista
def test_command_id_deterministic_per_match():
    c1 = M.to_command(_parsed(), "segunda-feb")["command_id"]
    c2 = M.to_command(_parsed(), "segunda-feb")["command_id"]
    assert c1 == c2


def test_command_id_differs_across_external_id():
    other = json.loads(json.dumps(FIXTURE))  # copy
    base_cmd = M.to_command(_parsed(), "segunda-feb")["command_id"]
    other_parsed = M.parse_boxscore(other, match_id="9999999", season_code=SEASON)
    other_cmd = M.to_command(other_parsed, "segunda-feb")["command_id"]
    assert base_cmd != other_cmd


# --- 9. --fixture --dry-run no exige FEB_SOURCE_URL/FEB_TOKEN
def test_dry_run_does_not_require_token_or_source(monkeypatch, capsys):
    monkeypatch.delenv("FEB_SOURCE_URL", raising=False)
    monkeypatch.delenv("FEB_TOKEN", raising=False)
    monkeypatch.setenv("FEB_SEASON_CODE", SEASON)
    monkeypatch.setenv("FEB_MATCH_ID", MATCH_ID)
    monkeypatch.setattr(_sys, "argv", [
        "ingest_match.py", "--fixture",
        str(ROOT / "tests/ingestion/fixtures/boxscore_2486864.json"),
        "--dry-run",
    ])
    rc = M.run()
    assert rc == 0
    out = capsys.readouterr().out
    assert "DRY_RUN" in out
    assert "external_id=2486864" in out
    assert "competition=SEGUNDA FEB" in out
    assert "scheduled_at=2025-10-18T19:00:00+01:00" in out
    assert "home_score=80" in out and "away_score=88" in out


# --- 10. --dry-run no hace POST
def test_dry_run_makes_no_http_post(monkeypatch, capsys):
    calls = {"n": 0}
    def boom(*a, **k):
        calls["n"] += 1
        raise AssertionError("POST should not run in dry-run")
    monkeypatch.setattr(M, "post_command", boom)
    monkeypatch.delenv("FEB_SOURCE_URL", raising=False)
    monkeypatch.delenv("FEB_TOKEN", raising=False)
    monkeypatch.setenv("FEB_SEASON_CODE", SEASON)
    monkeypatch.setenv("FEB_MATCH_ID", MATCH_ID)
    monkeypatch.setattr(_sys, "argv", [
        "ingest_match.py", "--fixture",
        str(ROOT / "tests/ingestion/fixtures/boxscore_2486864.json"),
        "--dry-run",
    ])
    rc = M.run()
    assert rc == 0
    assert calls["n"] == 0


# --- 11. token nunca aparece en salida dry-run
def test_token_never_in_dry_run_output(monkeypatch, capsys):
    fake_token = "FEB_TOKEN_VALUE_" + "0" * 40
    fake_key = "apikey_" + "1" * 40
    monkeypatch.setenv("FEB_TOKEN", fake_token)
    monkeypatch.setenv("FEB_API_KEY", fake_key)
    monkeypatch.delenv("FEB_SOURCE_URL", raising=False)
    monkeypatch.setenv("FEB_SEASON_CODE", SEASON)
    monkeypatch.setenv("FEB_MATCH_ID", MATCH_ID)
    monkeypatch.setattr(_sys, "argv", [
        "ingest_match.py", "--fixture",
        str(ROOT / "tests/ingestion/fixtures/boxscore_2486864.json"),
        "--dry-run",
    ])
    rc = M.run()
    assert rc == 0
    out = capsys.readouterr().out
    assert fake_token not in out
    assert fake_key not in out


# --- 12. payload cumple exactamente el schema existente (additionalProperties:false)
def test_command_payload_matches_contract_schema():
    schema = json.loads((ROOT / "contracts/commands/create_or_update_match.v1.json").read_text())
    cmd = M.to_command(_parsed(), "segunda-feb")
    required = schema["properties"]["payload"]["required"]
    payload = cmd["payload"]
    for r in required:
        assert r in payload, f"missing required payload field {r}"
    allowed = set(schema["properties"]["payload"]["properties"].keys())
    extra = set(payload.keys()) - allowed
    assert not extra, f"payload has extra props not in schema: {extra}"
