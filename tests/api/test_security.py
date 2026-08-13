"""FASE 11 + FASE 13 — Security: authn/authz, envelope integrity, headers, leaks.

FASE 13 additions: the client can no longer declare a role. Commands require an
API key (401 anonymous), and a principal below the command's minimum role is
rejected (403). Role claims in the envelope or payload are ignored — the
authenticated principal is the single source of identity and role.
"""

import json

from feb_score.api.main import create_app
from feb_score.infrastructure.logging import RecordingLogger
from feb_score.infrastructure.persistence.connection import SqliteDatabase
from feb_score.infrastructure.wiring import SqliteGateway

from api_helpers import create_payload


def test_oversized_payload_rejected_413(db_path):
    db = SqliteDatabase(db_path)
    db.migrate()
    gateway = SqliteGateway(db, logger=RecordingLogger())
    app = create_app(gateway, logger=RecordingLogger(), body_size_limit=256)
    from fastapi.testclient import TestClient

    client = TestClient(app)
    big_body = {"payload": {"padding": "x" * 2000}}
    resp = client.post(
        "/v1/commands/create_or_update_match",
        content=json.dumps(big_body),
        headers={"content-type": "application/json"},
    )
    assert resp.status_code == 413
    assert resp.json()["error"]["code"] == "PAYLOAD_TOO_LARGE"


def test_sql_injection_attempt_returns_404_not_error(client):
    resp = client.get("/v1/matches/2513600%27%20OR%20%271%27=%271")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "NOT_FOUND"


def test_errors_never_leak_stack_traces(client, db_path):
    from feb_score.infrastructure.persistence.repositories import SqliteMatchRepository

    from api_helpers import ready_to_finalize

    SqliteMatchRepository(SqliteDatabase(db_path)).save(ready_to_finalize())
    for _ in range(2):  # finalize twice: second is a domain-guarded replay, not a crash
        resp = client.post("/v1/commands/finalize_match", json={"payload": {"match_external_id": "2513600"}})
        assert "Traceback" not in resp.text
        assert "File \"" not in resp.text


def test_unknown_envelope_field_forbidden(client):
    # The client cannot smuggle an actor/role into the envelope (extra: forbid).
    resp = client.post(
        "/v1/commands/create_or_update_match",
        json={"payload": create_payload(), "actor": {"id": "a", "role": "system"}},
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "INVALID_BODY"


def test_security_headers_are_set(client):
    resp = client.post("/v1/commands/create_or_update_match", json={"payload": create_payload()})
    assert resp.headers["x-content-type-options"] == "nosniff"
    assert resp.headers["x-frame-options"] == "DENY"
    assert resp.headers["cache-control"] == "no-store"
    assert resp.headers["x-request-id"]  # correlation id present on every response


# ------------------------------------------------ FASE 13 authn / authz


def test_anonymous_command_is_rejected_401(client):
    resp = client.anon().post("/v1/commands/create_or_update_match", json={"payload": create_payload()})
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "UNAUTHENTICATED"


def test_anonymous_malformed_json_still_400(client):
    # Body parsing happens before authentication: malformed JSON is a 400,
    # not a 401, even without credentials.
    resp = client.anon().post(
        "/v1/commands/create_or_update_match",
        content="{not valid json",
        headers={"content-type": "application/json"},
    )
    assert resp.status_code == 400


def test_insufficient_role_rejected_403(client):
    # Approve_correction requires admin; an editor key is authenticated but
    # not authorized.
    resp = client.as_role("editor").post(
        "/v1/commands/approve_correction",
        json={"payload": {"proposal_id": "nope", "approved_by": {"id": "editor-1"}, "approved_at": "2026-02-02T12:00:00Z"}},
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "FORBIDDEN"


def test_payload_role_claim_cannot_escalate_privileges(client, db_path):
    """A client running with an EDITOR key cannot approve a correction by
    claiming role=admin in the payload: the domain check uses the authenticated
    principal's role, and the editor's own guard fires first (403)."""
    from feb_score.domain.match.model import Match
    from feb_score.infrastructure.persistence.repositories import SqliteMatchRepository

    from api_helpers import ready_to_finalize

    SqliteMatchRepository(SqliteDatabase(db_path)).save(ready_to_finalize())
    assert client.as_role("system").post(
        "/v1/commands/finalize_match", json={"payload": {"match_external_id": "2513600"}}
    ).status_code == 200

    from uuid import uuid4

    proposal_id = str(uuid4())
    resp = client.post(
        "/v1/commands/propose_correction",
        json={"command_id": proposal_id, "payload": {
            "match_external_id": "2513600",
            "proposed_by": {"id": "editor-1", "role": "editor"},
            "reason": "official score",
            "changes": [{"op": "update_score", "home_score": 80, "away_score": 77}],
        }},
    )
    assert resp.status_code == 200

    # editor key + payload claiming admin role -> 403, never approved.
    resp = client.as_role("editor").post(
        "/v1/commands/approve_correction",
        json={"payload": {
            "proposal_id": resp.json()["command_id"],
            "approved_by": {"id": "admin-1", "role": "admin"},
            "approved_at": "2026-02-02T12:00:00Z",
        }},
    )
    assert resp.status_code == 403


def test_system_principal_runs_any_command(client):
    resp = client.post("/v1/commands/create_or_update_match", json={"payload": create_payload()})
    assert resp.status_code == 200


def test_reads_contracts_and_health_are_public(client):
    for method, path in [
        ("get", "/v1/matches/absent"),
        ("get", "/v1/players/absent"),
        ("get", "/v1/teams/absent"),
        ("get", "/v1/competitions/absent"),
        ("get", "/v1/leaderboards/absent"),
        ("get", "/v1/correction-proposals/absent"),
        ("get", "/v1/contracts/create_or_update_match"),
        ("get", "/health"),
        ("get", "/ready"),
    ]:
        resp = client.anon().request(method, path)
        assert resp.status_code in (200, 404), f"{method} {path} -> {resp.status_code}"