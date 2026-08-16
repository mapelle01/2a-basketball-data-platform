"""FASE 22.4 — Round propagation + HTTP 429 retry tests (offline, mocks).

No FEB real, no API real, no production. Round propagation y retry se prueban
con monkeypatch sobre ingest_match / ingest_round / discover_matches.
"""
from __future__ import annotations

import importlib.util
import io
import json
import sys as _sys
import urllib.error
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = json.loads((ROOT / "tests/ingestion/fixtures/boxscore_2486864.json").read_text())
CALENDAR_HTML = (ROOT / "tests/ingestion/fixtures/calendario_jornadas_2025_2026.html").read_text(
    encoding="utf-8"
)

_spec = importlib.util.spec_from_file_location(
    "ingest_match", ROOT / "scripts" / "feb" / "ingest_match.py"
)
M = importlib.util.module_from_spec(_spec)
_sys.modules[_spec.name] = M
_spec.loader.exec_module(M)

SEASON = "2025-2026"
MATCH_ID = "2486864"


def _parsed(round_number=None):
    return M.parse_boxscore(FIXTURE, match_id=MATCH_ID, season_code=SEASON,
                            round_number=round_number)


def _http_error(code, retry_after=None):
    headers = {}
    if retry_after is not None:
        headers["Retry-After"] = str(retry_after)
    return urllib.error.HTTPError(
        "http://test", code, f"HTTP {code}", headers, io.BytesIO(b"{}")
    )


# --- FASE 22.4.A: propagación de la jornada real ---------------------------------

def test_parse_boxscore_stores_round_number():
    assert _parsed(round_number=7)["round_number"] == 7


def test_parse_boxscore_round_none_when_absent():
    assert _parsed()["round_number"] is None


def test_parse_boxscore_round_from_discovery_ranges():
    assert _parsed(round_number=1)["round_number"] == 1
    assert _parsed(round_number=26)["round_number"] == 26


def test_to_command_payload_has_real_round_number():
    cmd = M.to_command(_parsed(round_number=7), "segunda-feb")
    assert cmd["payload"]["round_number"] == 7


def test_to_command_payload_omits_round_when_unknown():
    cmd = M.to_command(_parsed(), "segunda-feb")
    assert "round_number" not in cmd["payload"]


def test_to_command_round_number_not_hardcoded_to_one():
    for rn in (2, 3, 26):
        assert M.to_command(_parsed(round_number=rn), "segunda-feb")["payload"]["round_number"] == rn


def test_to_command_round_payload_matches_contract_schema():
    schema = json.loads((ROOT / "contracts/commands/create_or_update_match.v1.json").read_text())
    for rn in (1, 7, 26):
        payload = M.to_command(_parsed(round_number=rn), "segunda-feb")["payload"]
        allowed = set(schema["properties"]["payload"]["properties"].keys())
        assert set(payload.keys()) - allowed == set()
    # round_number sigue siendo opcional en el contrato
    assert "round_number" not in schema["properties"]["payload"]["required"]


# --- FASE 22.4.A: la jornada del discovery llega al command (ingest_round) --------

def test_ingest_round_propagates_ref_round_to_command(monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "ingest_round", ROOT / "scripts" / "feb" / "ingest_round.py"
    )
    R = importlib.util.module_from_spec(spec)
    _sys.modules[spec.name] = R
    spec.loader.exec_module(R)

    monkeypatch.setenv("FEB_TOKEN", "tok" + "0" * 40)
    monkeypatch.setenv("FEB_TARGET_API", "http://api.test")
    monkeypatch.setenv("FEB_API_KEY", "key" + "1" * 40)

    ref = R.DM.MatchRef(
        external_id=2486864,
        round_number=12,
        scheduled_at="2025-12-13T00:00:00+01:00",
        home_team="BUENO ARENAS ALBACETE BASKET",
        away_team="LOBE HUESCA LA MAGIA",
        source_url="https://baloncestoenvivo.feb.es/Partido.aspx?p=2486864",
    )
    monkeypatch.setattr(R.DM, "discover_matches", lambda season, round_, **kw: [ref])
    monkeypatch.setattr(R.IM, "fetch_feb_boxscore", lambda match_id, token, base: FIXTURE)

    seen = {}
    def post(target, api_key, cmd):
        seen["payload"] = cmd["payload"]
        return {"status": 200, "body": {"ok": True}}
    monkeypatch.setattr(R.IM, "post_command", post)
    monkeypatch.setattr(R.IM, "post_stats_command",
                        lambda target, api_key, cmd: {"status": 200, "body": {"ok": True}})

    rc = R.run_round(SEASON, 12)
    assert rc == 0
    assert seen["payload"]["round_number"] == 12


def test_ingest_round_distinct_rounds_reach_command(monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "ingest_round", ROOT / "scripts" / "feb" / "ingest_round.py"
    )
    R = importlib.util.module_from_spec(spec)
    _sys.modules[spec.name] = R
    spec.loader.exec_module(R)

    monkeypatch.setenv("FEB_TOKEN", "tok" + "0" * 40)
    monkeypatch.setenv("FEB_TARGET_API", "http://api.test")
    monkeypatch.setenv("FEB_API_KEY", "key" + "1" * 40)

    refs = [
        R.DM.MatchRef(external_id=2486900 + i, round_number=rn,
                      scheduled_at="2025-10-04T00:00:00+01:00",
                      home_team=f"H{i}", away_team=f"A{i}",
                      source_url=f"https://baloncestoenvivo.feb.es/Partido.aspx?p={2486900 + i}")
        for i, rn in enumerate((1, 2, 3), start=0)
    ]
    monkeypatch.setattr(R.DM, "discover_matches", lambda season, round_, **kw: refs)
    monkeypatch.setattr(R.IM, "fetch_feb_boxscore", lambda match_id, token, base: FIXTURE)

    seen = {}
    def post(target, api_key, cmd):
        seen[cmd["payload"]["external_id"]] = cmd["payload"].get("round_number")
        return {"status": 200, "body": {"ok": True}}
    monkeypatch.setattr(R.IM, "post_command", post)
    monkeypatch.setattr(R.IM, "post_stats_command",
                        lambda target, api_key, cmd: {"status": 200, "body": {"ok": True}})

    rc = R.run_round(SEASON, 1)
    assert rc == 0
    assert seen == {"2486900": 1, "2486901": 2, "2486902": 3}


def test_resolve_round_for_match_from_calendar_fixture():
    spec = importlib.util.spec_from_file_location(
        "discover_matches", ROOT / "scripts" / "feb" / "discover_matches.py"
    )
    DM = importlib.util.module_from_spec(spec)
    _sys.modules[spec.name] = DM
    spec.loader.exec_module(DM)
    assert DM.resolve_round_for_match(SEASON, "2486849", calendar_html=CALENDAR_HTML) == 1
    assert DM.resolve_round_for_match(SEASON, "2486852", calendar_html=CALENDAR_HTML) == 2
    assert DM.resolve_round_for_match(SEASON, "9999999", calendar_html=CALENDAR_HTML) is None


# --- FASE 22.4.B: retry de HTTP 429 (bounded, con backoff y Retry-After) ---------

def test_retry_succeeds_after_single_429():
    attempts = {"n": 0}
    sleeps = []

    def open_fn():
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise _http_error(429)
        return "ok"

    result = M.request_with_retry(open_fn, max_retries=3, base_backoff=1.0,
                                  sleep=sleeps.append)
    assert result == "ok"
    assert attempts["n"] == 2
    assert sleeps == [1.0]


def test_retry_backoff_exponential():
    attempts = {"n": 0}
    sleeps = []

    def open_fn():
        attempts["n"] += 1
        if attempts["n"] <= 2:
            raise _http_error(429)
        return "ok"

    M.request_with_retry(open_fn, max_retries=5, base_backoff=1.0, sleep=sleeps.append)
    assert sleeps == [1.0, 2.0]


def test_retry_honors_retry_after_header():
    attempts = {"n": 0}
    sleeps = []

    def open_fn():
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise _http_error(429, retry_after=7)
        return "ok"

    M.request_with_retry(open_fn, max_retries=3, base_backoff=1.0, sleep=sleeps.append)
    assert sleeps == [7.0]


def test_retry_exhausts_after_max_retries():
    attempts = {"n": 0}
    sleeps = []

    def open_fn():
        attempts["n"] += 1
        raise _http_error(429)

    with pytest.raises(urllib.error.HTTPError) as ei:
        M.request_with_retry(open_fn, max_retries=3, base_backoff=1.0, sleep=sleeps.append)
    assert ei.value.code == 429
    assert attempts["n"] == 4  # 1 intento + 3 reintentos
    assert len(sleeps) == 3


def test_retry_zero_max_retries_no_backoff():
    attempts = {"n": 0}
    sleeps = []

    def open_fn():
        attempts["n"] += 1
        raise _http_error(429)

    with pytest.raises(urllib.error.HTTPError):
        M.request_with_retry(open_fn, max_retries=0, base_backoff=1.0, sleep=sleeps.append)
    assert attempts["n"] == 1
    assert sleeps == []


@pytest.mark.parametrize("code", [400, 401, 403, 404, 500, 503])
def test_non_429_statuses_never_retried(code):
    attempts = {"n": 0}
    sleeps = []

    def open_fn():
        attempts["n"] += 1
        raise _http_error(code)

    with pytest.raises(urllib.error.HTTPError) as ei:
        M.request_with_retry(open_fn, max_retries=3, base_backoff=1.0, sleep=sleeps.append)
    assert ei.value.code == code
    assert attempts["n"] == 1  # nunca reintenta
    assert sleeps == []


def test_retry_uses_default_sleep_when_http_error_after_429_not_retried():
    """El helper por defecto usa time.sleep (no se llama en tests); con 401 no duerme."""
    attempts = {"n": 0}

    def open_fn():
        attempts["n"] += 1
        raise _http_error(401)

    with pytest.raises(urllib.error.HTTPError):
        M.request_with_retry(open_fn, max_retries=3, base_backoff=1.0)
    assert attempts["n"] == 1