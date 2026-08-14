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


# --- 13. el POST HTTP envía SOLO {command_id, payload}; nunca meta/actor (FASE 13 envelope)
def test_post_command_http_body_has_no_meta_or_actor(monkeypatch):
    sent = {}

    class _FakeResp:
        status = 200
        def read(self):
            return b'{"ok": true}'

    class _FakeHTTP:
        def __init__(self, req, timeout=None):
            sent["url"] = req.full_url
            sent["method"] = req.get_method()
            sent["body"] = req.data.decode("utf-8")
            sent["auth"] = req.headers.get("Authorization")
        def __enter__(self):
            return _FakeResp()
        def __exit__(self, *a):
            return False

    monkeypatch.setattr(M.urllib.request, "urlopen", lambda *a, **k: _FakeHTTP(a[0]))
    cmd = M.to_command(_parsed(), "segunda-feb")
    res = M.post_command("http://api.test", "the-api-key", cmd)
    assert res["status"] == 200

    posted = json.loads(sent["body"])
    assert set(posted.keys()) == {"command_id", "payload"}
    assert "meta" not in posted
    assert "actor" not in posted
    assert posted["command_id"] == cmd["command_id"]
    assert posted["payload"] == cmd["payload"]
    assert sent["method"] == "POST"
    # Auth header must carry the api key (never printed here), but no secret literal in body
    assert "the-api-key" not in sent["body"]
    assert "meta" not in sent["body"]


# --- FASE 21.B3: upsert_match_stats command from the real fixture

def test_stats_command_contract_compliant():
    schema = json.loads((ROOT / "contracts/commands/upsert_match_stats.v1.json").read_text())
    import jsonschema
    from jsonschema import FormatChecker
    cmd = M.to_stats_command(_parsed(), "segunda-feb")
    jsonschema.validate(cmd, schema, format_checker=FormatChecker())


def test_stats_command_reid_maps_exactly():
    cmd = M.to_stats_command(_parsed(), "segunda-feb")
    payload = cmd["payload"]
    reid = next(p for p in payload["player_stats"] if p["player_external_id"] == "2813013")
    assert reid["points"] == 12
    assert reid["rebounds"] == 6
    assert reid["assists"] == 1
    assert reid["steals"] == 1
    assert reid["blocks"] == 0
    assert reid["turnovers"] == 0
    assert reid["minutes"] == pytest.approx(33.517, abs=0.01)
    assert reid["played_at"] == "2025-10-18T19:00:00+01:00"


def test_stats_command_has_all_players_both_teams():
    cmd = M.to_stats_command(_parsed(), "segunda-feb")
    payload = cmd["payload"]
    assert len(payload["player_stats"]) == 21  # home 10 + away 11
    home_ids = {p["player_external_id"] for p in payload["player_stats"]
                if p["team_external_id"] == "979897"}
    away_ids = {p["player_external_id"] for p in payload["player_stats"]
                if p["team_external_id"] == "981281"}
    assert len(home_ids) == 10
    assert len(away_ids) == 11


def test_stats_command_team_totals_from_total():
    cmd = M.to_stats_command(_parsed(), "segunda-feb")
    payload = cmd["payload"]
    home, away = payload["home_team_stats"], payload["away_team_stats"]
    assert home["team_external_id"] == "979897"
    assert home["points_for"] == 80 and home["points_against"] == 88
    assert home["field_goals_made"] == 31 and home["field_goals_attempted"] == 68
    assert home["three_points_made"] == 8 and home["three_points_attempted"] == 25
    assert home["free_throws_made"] == 10 and home["free_throws_attempted"] == 23
    assert home["turnovers"] == 9 and home["rebounds"] == 34
    assert away["team_external_id"] == "981281"
    assert away["points_for"] == 88 and away["points_against"] == 80


def test_stats_command_id_deterministic_and_distinct_from_match():
    s1 = M.to_stats_command(_parsed(), "segunda-feb")["command_id"]
    s2 = M.to_stats_command(_parsed(), "segunda-feb")["command_id"]
    assert s1 == s2
    match_cmd = M.to_command(_parsed(), "segunda-feb")["command_id"]
    assert s1 != match_cmd


def test_stats_command_leaves_create_or_update_match_raw_intact():
    """B3 keeps raw contract-compliant: create_or_update_match payload has NO
    player/team stats; raw only carries boxscore_ref/teamstats_ref."""
    cmd = M.to_command(_parsed(), "segunda-feb")
    payload = cmd["payload"]
    assert "player_stats" not in payload
    assert "home_team_stats" not in payload and "away_team_stats" not in payload
    assert set(payload["raw"].keys()) == {"boxscore_ref", "teamstats_ref"}


def test_stats_command_http_body_has_no_meta_or_actor(monkeypatch):
    sent = {}

    class _FakeResp:
        status = 200
        def read(self):
            return b'{"ok": true}'

    class _FakeHTTP:
        def __init__(self, req, timeout=None):
            sent["url"] = req.full_url
            sent["body"] = req.data.decode("utf-8")
        def __enter__(self):
            return _FakeResp()
        def __exit__(self, *a):
            return False

    monkeypatch.setattr(M.urllib.request, "urlopen", lambda *a, **k: _FakeHTTP(a[0]))
    cmd = M.to_stats_command(_parsed(), "segunda-feb")
    res = M.post_stats_command("http://api.test", "the-api-key", cmd)
    assert res["status"] == 200
    assert sent["url"].endswith("/v1/commands/upsert_match_stats")
    posted = json.loads(sent["body"])
    assert set(posted.keys()) == {"command_id", "payload"}


def test_stats_command_without_player_stats_is_valid():
    """A match with no player stats (optional field absent) still yields a
    contract-compliant command with an empty player_stats list."""
    parsed = _parsed()
    parsed["stats"] = {"home": [], "away": []}
    cmd = M.to_stats_command(parsed, "segunda-feb")
    payload = cmd["payload"]
    assert payload["player_stats"] == []
    assert payload["home_team_stats"]["team_external_id"] == "979897"


def test_stats_command_optional_player_fields_default():
    """A player missing optional FEB fields (st/bs/to absent) maps to zeros."""
    parsed = _parsed()
    sample = parsed["stats"]["home"][0]
    minimal = {"id": sample["id"], "no": "7", "name": "MIN", "min": 1200,
               "pts": 5, "reb": 2, "assist": 1, "val": 3}
    parsed["stats"]["home"] = [minimal]
    parsed["stats"]["away"] = []
    cmd = M.to_stats_command(parsed, "segunda-feb")
    payload = cmd["payload"]
    p = payload["player_stats"][0]
    assert p["steals"] == 0 and p["blocks"] == 0 and p["turnovers"] == 0
