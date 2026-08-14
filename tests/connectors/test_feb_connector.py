from __future__ import annotations

from connectors.feb.client import FEBClient
from connectors.feb.sink import ProductionSink, build_match_payload


RESULTS_HTML = """
<html><body>
<h1>Resultados Jornada 5</h1>
<table>
<tr><th>Equipos</th><th>Resultado</th><th>Fecha</th><th>Hora</th></tr>
<tr>
  <td>TEAM HOME - TEAM AWAY</td>
  <td><a href="Partido.aspx?med=0&p=2487791">74-76</a></td>
  <td>02/11/2025</td><td>18:00</td>
</tr>
</table>
</body></html>
"""

MATCH_HTML = """
<html><body><div id="contentToken"><input value="secret-token" /></div></body></html>
"""


class FakeResponse:
    def __init__(self, payload=None, text=""):
        self.payload = payload
        self.text = text

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self):
        self.headers = {}
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append(("GET", url, kwargs))
        if "resultados.aspx" in url:
            return FakeResponse(text=RESULTS_HTML)
        if "Partido.aspx" in url:
            return FakeResponse(text=MATCH_HTML)
        return FakeResponse(payload={"BOXSCORE": {"TEAM": []}})

    def post(self, url, **kwargs):
        self.calls.append(("POST", url, kwargs))
        return FakeResponse(payload={"status": "accepted", "command_id": "cmd"})


def test_results_parser_extracts_match_and_round():
    client = FEBClient(session=FakeSession())
    matches = client.list_matches(RESULTS_HTML)

    assert len(matches) == 1
    match = matches[0]
    assert match.external_id == "2487791"
    assert match.home_team_name == "TEAM HOME"
    assert match.away_team_name == "TEAM AWAY"
    assert match.home_score == 74
    assert match.away_score == 76
    assert match.round_number == 5
    assert match.status == "FINALIZED"


def test_live_stats_uses_token_from_match_page_without_logging_or_requiring_static_feb_credentials():
    session = FakeSession()
    client = FEBClient(session=session)
    match = client.list_matches(RESULTS_HTML)[0]

    responses = client.fetch_live_stats(match, MATCH_HTML, endpoints=("BoxScore",))

    assert "BoxScore" in responses
    method, url, kwargs = session.calls[-1]
    assert method == "GET"
    assert url.endswith("/BoxScore/2487791")
    assert kwargs["headers"]["Authorization"] == "Bearer secret-token"


def test_payload_uses_stable_team_ids_and_v1_shape():
    match = FEBClient(session=FakeSession()).list_matches(RESULTS_HTML)[0]
    responses = {
        "BoxScore": {
            "BOXSCORE": {
                "TEAM": [
                    {"id": "100", "name": "TEAM HOME"},
                    {"id": "200", "name": "TEAM AWAY"},
                ]
            }
        }
    }

    payload = build_match_payload(match, responses, source_url=match.match_url)

    assert payload["external_id"] == "2487791"
    assert payload["season_code"] == "2025-2026"
    assert payload["home_team"]["external_id"] == "100"
    assert payload["away_team"]["external_id"] == "200"
    assert payload["source"]["id"] == "feb:2487791"
    assert payload["raw"]["boxscore_ref"].endswith("#BoxScore")
    assert "score_summary" not in payload


def test_production_sink_uses_bearer_key_and_deterministic_idempotency_key():
    session = FakeSession()
    sink = ProductionSink("https://example.test", "raw-api-key", session=session)
    match = FEBClient(session=FakeSession()).list_matches(RESULTS_HTML)[0]
    payload = build_match_payload(match, {}, source_url=match.match_url)

    first = sink.send_match(match, payload)
    second = sink.send_match(match, payload)

    assert first["status"] == "accepted"
    assert second["status"] == "accepted"
    post_calls = [call for call in session.calls if call[0] == "POST"]
    assert len(post_calls) == 2
    assert post_calls[0][2]["headers"]["Authorization"] == "Bearer raw-api-key"
    assert post_calls[0][2]["json"]["command_id"] == post_calls[1][2]["json"]["command_id"]
