"""FASE 22.5 — OESTE group support tests (offline, mocks/fakes).

No FEB real, no API real, no production. El calendario OESTE se prueba contra el
fixture controlado `calendario_oeste_2025_2026.html` (HTML ASP.NET con el
dropdown de grupos y hidden fields) y los fetch/POST se simulan con monkeypatch.
"""
from __future__ import annotations

import importlib.util
import json
import sys as _sys
import urllib.parse
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
ESTE_FIXTURE = (ROOT / "tests/ingestion/fixtures/calendario_jornadas_2025_2026.html").read_text(
    encoding="utf-8"
)
OESTE_FIXTURE = (ROOT / "tests/ingestion/fixtures/calendario_oeste_2025_2026.html").read_text(
    encoding="utf-8"
)
BOXSCORE = json.loads((ROOT / "tests/ingestion/fixtures/boxscore_2486864.json").read_text())

_spec = importlib.util.spec_from_file_location(
    "discover_matches", ROOT / "scripts" / "feb" / "discover_matches.py"
)
M = importlib.util.module_from_spec(_spec)
_sys.modules[_spec.name] = M
_spec.loader.exec_module(M)

_spec_r = importlib.util.spec_from_file_location(
    "ingest_round", ROOT / "scripts" / "feb" / "ingest_round.py"
)
R = importlib.util.module_from_spec(_spec_r)
_sys.modules[_spec_r.name] = R
_spec_r.loader.exec_module(R)

SEASON = "2025-2026"
OESTE_ROUND1_IDS = list(range(2487759, 2487766))  # 2487759..2487765 (7 partidos)
OESTE_ROUND2_IDS = list(range(2487766, 2487773))  # 2487766..2487772 (7 partidos)
ENV = {"FEB_TOKEN": "tok-" + "0" * 40, "FEB_TARGET_API": "http://api.test", "FEB_API_KEY": "key-" + "1" * 40}


# --- 1. parse del calendario OESTE (jornadas correctas)
def test_oeste_calendar_parse_jornadas():
    by_round = M.parse_calendar(OESTE_FIXTURE)
    assert set(by_round) == {1, 2}
    assert len(by_round[1]) == 7
    assert len(by_round[2]) == 7


# --- 2. external IDs correctos de la jornada 1 OESTE
def test_oeste_external_ids_round1():
    by_round = M.parse_calendar(OESTE_FIXTURE)
    assert sorted(r.external_id for r in by_round[1]) == OESTE_ROUND1_IDS


# --- 3. external IDs correctos de la jornada 2 OESTE
def test_oeste_external_ids_round2():
    by_round = M.parse_calendar(OESTE_FIXTURE)
    assert sorted(r.external_id for r in by_round[2]) == OESTE_ROUND2_IDS


# --- 4. round_number y scheduled_at correctos
def test_oeste_round_number_and_scheduled_at():
    by_round = M.parse_calendar(OESTE_FIXTURE)
    assert {r.round_number for r in by_round[1]} == {1}
    assert {r.round_number for r in by_round[2]} == {2}
    assert by_round[1][0].scheduled_at == "2025-10-04T00:00:00+01:00"
    assert by_round[2][0].scheduled_at == "2025-10-11T00:00:00+01:00"


# --- 5. equipos OESTE (home/away) y source_url
def test_oeste_teams_and_source_url():
    by_round = M.parse_calendar(OESTE_FIXTURE)
    by_id = {r.external_id: r for r in by_round[1]}
    assert by_id[2487759].home_team == "UEMC BALONCESTO VALLADOLID"
    assert by_id[2487759].away_team == "CLUB BALONCESTO TOLEDO BASKET"
    assert by_id[2487765].home_team == "BIELE ISB"
    assert by_id[2487765].away_team == "LOGROBASKET LOGI7"
    assert by_id[2487759].source_url == "https://baloncestoenvivo.feb.es/Partido.aspx?p=2487759"


# --- 6. dedupe de IDs repetidos (fixture repite 2487759 en la jornada 1)
def test_oeste_dedupe_repeated_ids():
    by_round = M.parse_calendar(OESTE_FIXTURE)
    ids = [r.external_id for r in by_round[1]]
    assert len(ids) == len(set(ids)) == 7


# --- 7. discover_matches con group="OESTE" vía fixture
def test_oeste_discover_group_explicit():
    refs = M.discover_matches(SEASON, 1, calendar_html=OESTE_FIXTURE, group="OESTE")
    assert [r.external_id for r in refs] == OESTE_ROUND1_IDS


# --- 8. ESTE backward compat: group="ESTE" y default idénticos
def test_este_backward_compat_group_este():
    default = M.discover_matches(SEASON, 1, calendar_html=ESTE_FIXTURE)
    este = M.discover_matches(SEASON, 1, calendar_html=ESTE_FIXTURE, group="ESTE")
    assert default == este
    assert [r.external_id for r in este] == [2486849, 2486850, 2486851]


# --- 9. grupo no soportado -> ConfigError (CLI devuelve 2)
@pytest.mark.parametrize("group", ["SUR", "CENTRO", ""])
def test_unsupported_group_raises(group):
    with pytest.raises(M.ConfigError):
        M.discover_matches(SEASON, 1, calendar_html=OESTE_FIXTURE, group=group)


# --- 10. extracción del valor del dropdown de grupos desde el HTML ASP.NET
def test_grupo_value_from_html():
    assert M._grupo_value(OESTE_FIXTURE, "ESTE") == "88879"
    assert M._grupo_value(OESTE_FIXTURE, "OESTE") == "88880"
    assert M._grupo_value(OESTE_FIXTURE, "SUR") is None


# --- 11. extracción de hidden fields del formulario ASP.NET
def test_hidden_inputs_from_html():
    hidden = M._hidden_inputs(OESTE_FIXTURE)
    assert hidden.get("__VIEWSTATE") == "/wEPDwUKLT"
    assert hidden.get("__EVENTVALIDATION") == "/wEdAA"
    assert hidden.get("_ctl0:token") == "eyJhbGciOiJIUzI1NiJ9.eyJpc3MiOiJmZWItZml4dHVyZS1ub3QtYS1yZWFsLXRva2VuIn0.sig"


# --- 12. POST ASP.NET: construye los datos correctos y reenvía hidden fields
def test_post_grupo_posts_correct_data(monkeypatch):
    sent = {}

    class FakeResp:
        status = 200

        def read(self):
            return OESTE_FIXTURE.encode("utf-8")

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout=None):
        sent["url"] = req.full_url
        sent["method"] = req.get_method()
        sent["body"] = req.data.decode("utf-8") if req.data else None
        return FakeResp()

    monkeypatch.setattr(M.urllib.request, "urlopen", fake_urlopen)

    html_text = M._post_grupo("https://baloncestoenvivo.feb.es/calendario/segundafeb/2/2025", OESTE_FIXTURE, "OESTE")
    assert html_text == OESTE_FIXTURE
    assert sent["method"] == "POST"
    assert sent["url"].startswith("https://baloncestoenvivo.feb.es/calendario/segundafeb/2/2025")
    body = urllib.parse.parse_qs(sent["body"])
    # la URL del action es relativa; urljoin sobre la base
    assert sent["url"] == urllib.parse.urljoin("https://baloncestoenvivo.feb.es/calendario/segundafeb/2/2025", "/calendario/segundafeb/2/2025")
    assert body.get("_ctl0:MainContentPlaceHolderMaster:gruposDropDownList") == ["88880"]
    assert body.get("__VIEWSTATE") == ["/wEPDwUKLT"]
    assert body.get("_ctl0:token") == ["eyJhbGciOiJIUzI1NiJ9.eyJpc3MiOiJmZWItZml4dHVyZS1ub3QtYS1yZWFsLXRva2VuIn0.sig"]
    assert body.get("__EVENTTARGET") == ["_ctl0$MainContentPlaceHolderMaster$gruposDropDownList"]


# --- 13. fetch_calendar_group: ESTE usa GET (sin POST)
def test_fetch_calendar_group_este_no_post(monkeypatch):
    called = {}

    def fake_fetch(url):
        called["url"] = url
        return ESTE_FIXTURE

    monkeypatch.setattr(M, "fetch_calendar", fake_fetch)
    monkeypatch.setattr(M, "_post_grupo", lambda *a: (_ for _ in ()).throw(AssertionError("no POST en ESTE")))

    html_text = M.fetch_calendar_group(SEASON, "ESTE")
    assert html_text == ESTE_FIXTURE
    assert "calendario.aspx" in called["url"]


# --- 14. fetch_calendar_group: OESTE hace GET + POST
def test_fetch_calendar_group_oeste_posts(monkeypatch):
    calls = {}

    def fake_fetch(url):
        calls["fetch"] = url
        return OESTE_FIXTURE  # página base con dropdown + hidden fields

    def fake_post(base_url, page_html, group):
        calls["post"] = (base_url, group)
        return "<html>OESTE calendar</html>"

    monkeypatch.setattr(M, "fetch_calendar", fake_fetch)
    monkeypatch.setattr(M, "_post_grupo", fake_post)

    html_text = M.fetch_calendar_group(SEASON, "OESTE")
    assert html_text == "<html>OESTE calendar</html>"
    assert calls["post"] == ("https://baloncestoenvivo.feb.es/calendario.aspx?g=2&t=2025&nm=segundafeb", "OESTE")


# --- 15. grupo inválido en fetch_calendar_group -> ConfigError
def test_fetch_calendar_group_invalid_group(monkeypatch):
    monkeypatch.setattr(M, "fetch_calendar", lambda url: ESTE_FIXTURE)
    with pytest.raises(M.ConfigError):
        M.fetch_calendar_group(SEASON, "SUR")


# --- 16. resolve_round_for_match con group="OESTE"
def test_oeste_resolve_round_for_match():
    assert M.resolve_round_for_match(SEASON, "2487759", calendar_html=OESTE_FIXTURE, group="OESTE") == 1
    assert M.resolve_round_for_match(SEASON, "2487772", calendar_html=OESTE_FIXTURE, group="OESTE") == 2
    assert M.resolve_round_for_match(SEASON, "9999999", calendar_html=OESTE_FIXTURE, group="OESTE") is None


# --- 17. ingest_round con group="OESTE" (dry-run; reutiliza discovery)
def test_ingest_round_oeste_dry_run(monkeypatch, capsys):
    refs = [
        R.DM.MatchRef(
            external_id=eid, round_number=1,
            scheduled_at="2025-10-04T00:00:00+01:00",
            home_team="HOME", away_team="AWAY",
            source_url=f"https://baloncestoenvivo.feb.es/Partido.aspx?p={eid}",
        )
        for eid in OESTE_ROUND1_IDS
    ]
    calls = {}
    monkeypatch.setattr(R.DM, "discover_matches", lambda season, round_, **kw: (calls.update(group=kw.get("group")), refs)[1])

    rc = R.run_round(SEASON, 1, group="OESTE", dry_run=True)
    out = capsys.readouterr().out
    assert calls["group"] == "OESTE"
    assert rc == 0
    assert "group=OESTE" in out
    assert "discovered=7" in out
    assert "POST disabled" in out


# --- 18. ingest_season con group="OESTE" (dry-run; usa fetch_calendar_group)
def test_ingest_season_oeste_dry_run(monkeypatch, capsys):
    _spec_s = importlib.util.spec_from_file_location(
        "ingest_season", ROOT / "scripts" / "feb" / "ingest_season.py"
    )
    S = importlib.util.module_from_spec(_spec_s)
    _sys.modules[_spec_s.name] = S
    _spec_s.loader.exec_module(S)

    calls = {}
    monkeypatch.setattr(S.DM, "fetch_calendar_group", lambda season, group: (calls.update(group=group), OESTE_FIXTURE)[1])
    monkeypatch.setattr(S.IR, "run_round", lambda *a, **k: (_ for _ in ()).throw(AssertionError("dry-run: no run_round")))

    rc = S.run_season(SEASON, group="OESTE", dry_run=True)
    out = capsys.readouterr().out
    assert calls["group"] == "OESTE"
    assert rc == 0
    assert "rounds=2" in out
    assert "matches=14" in out
    assert "DRY_RUN" in out


# --- 19. los secretos (hidden _ctl0:token) nunca aparecen en la salida
def test_oeste_token_never_in_output(monkeypatch, capsys):
    token = "eyJhbGciOiJIUzI1NiJ9.eyJpc3MiOiJmZWItZml4dHVyZS1ub3QtYS1yZWFsLXRva2VuIn0.sig"
    sent = {}

    class FakeResp:
        status = 200

        def read(self):
            return "<html>no token here</html>".encode("utf-8")

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout=None):
        sent["body"] = req.data.decode("utf-8") if req.data else None
        return FakeResp()

    monkeypatch.setattr(M.urllib.request, "urlopen", fake_urlopen)
    html_text = M._post_grupo("https://baloncestoenvivo.feb.es/calendario/segundafeb/2/2025", OESTE_FIXTURE, "OESTE")
    out = capsys.readouterr().out
    assert token in sent["body"]  # el token se reenvía al servidor...
    assert token not in out  # ... pero jamás se imprime
    assert token not in html_text


# --- 20. CLI: --group inválido devuelve 2; --group OESTE con fetch OK devuelve 0
def test_cli_exit_2_bad_group(monkeypatch, capsys):
    monkeypatch.setattr(_sys, "argv", ["feb-discover", "--season", SEASON, "--round", "1", "--group", "SUR"])
    with pytest.raises(SystemExit) as exc:
        M.run()
    assert exc.value.code == 2


def test_cli_exit_0_oeste(monkeypatch, capsys):
    refs = M.parse_calendar(OESTE_FIXTURE)[1]
    monkeypatch.setattr(M, "discover_matches", lambda season, round_, group="ESTE", **kw: refs)
    monkeypatch.setattr(_sys, "argv", ["feb-discover", "--season", SEASON, "--round", "1", "--group", "OESTE"])
    assert M.run() == 0
    out = capsys.readouterr().out
    assert "discovered=7" in out
    assert "2487759" in out


# --- 21. ingest_round integración completa (no dry-run) con group="OESTE"
def test_ingest_round_oeste_full(monkeypatch, capsys):
    for k, v in ENV.items():
        monkeypatch.setenv(k, v)
    refs = [
        R.DM.MatchRef(
            external_id=OESTE_ROUND1_IDS[0], round_number=1,
            scheduled_at="2025-10-04T00:00:00+01:00",
            home_team="HOME", away_team="AWAY",
            source_url=f"https://baloncestoenvivo.feb.es/Partido.aspx?p={OESTE_ROUND1_IDS[0]}",
        )
    ]
    calls = {}
    monkeypatch.setattr(R.DM, "discover_matches", lambda season, round_, **kw: (calls.update(group=kw.get("group")), refs)[1])
    monkeypatch.setattr(R.IM, "fetch_feb_boxscore", lambda match_id, token, base: BOXSCORE)
    monkeypatch.setattr(R.IM, "post_command", lambda target, api_key, cmd: {"status": 200, "body": {"ok": True}})
    monkeypatch.setattr(R.IM, "post_stats_command", lambda target, api_key, cmd: {"status": 200, "body": {"ok": True}})

    rc = R.run_round(SEASON, 1, group="OESTE")
    out = capsys.readouterr().out
    assert calls["group"] == "OESTE"
    assert rc == 0
    assert "match_ok=1" in out
    assert "stats_ok=1" in out
    assert "failed=0" in out