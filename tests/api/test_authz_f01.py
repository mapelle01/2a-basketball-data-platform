"""FASE 14 closure — F-01: `system` as an explicit internal principal.

The contract schemas and the domain must agree with the AuthZ policy
(COMMAND_ROLES). `system` is a valid authenticated principal (>= admin); the
four commands whose `actor.role` enums rejected it no longer do, and the domain
approval guard accepts any admin-level principal. The client can never declare
a role (envelope/`actor` rejected, payload role ignored); the principal is the
single source of identity and role.

These tests prove:
1. `system` runs exactly the commands COMMAND_ROLES grants (and only those).
2. A client cannot forge `system`/`admin` to escalate privileges.
3. Invalid roles still fail as 401/403/422 (fail-closed).
4. Other roles keep their exact current permissions (no regression).
"""

import pytest

from feb_score.api.auth import ApiKeyAuthenticationProvider
from feb_score.domain.player.model import Player
from feb_score.domain.team.model import Team
from feb_score.domain.value_objects import ExternalId, PlayerId, TeamId
from feb_score.infrastructure.persistence.connection import SqliteDatabase
from feb_score.infrastructure.persistence.repositories import (
    SqliteMatchRepository,
    SqlitePlayerRepository,
    SqliteTeamRepository,
)

from api_helpers import auth_header, create_payload, ready_to_finalize


def _payload(command_type, role):
    return {
        "create_or_update_match": create_payload(),
        "finalize_match": {"match_external_id": "2513600"},
        "propose_correction": {
            "match_external_id": "2513600",
            "proposed_by": {"id": "editor-1", "role": role},
            "reason": "official score",
            "changes": [{"op": "update_score", "home_score": 80, "away_score": 77}],
        },
        "approve_correction": {
            "proposal_id": "00000000-0000-0000-0000-000000000000",
            "approved_by": {"id": "admin-1", "role": role},
            "approved_at": "2026-02-02T12:00:00Z",
        },
        "register_player_to_squad": {
            "player_external_id": "pl-987",
            "team_external_id": "team-123",
            "season_code": "2025-2026",
            "registered_from": "2025-08-01T00:00:00Z",
        },
        "generate_standing_snapshot": {
            "season_code": "2025-2026",
            "as_of": "2026-02-01T23:59:59Z",
            "rules_version": "rules-v1",
        },
        "generate_leaderboard": {
            "season_code": "2025-2026",
            "category": "points_per_game",
            "min_games": 0,
            "top_n": 10,
            "competition_id": "feb-comp",
        },
        "compute_player_rating": {
            "player_external_id": "pl-1",
            "season_code": "2025-2026",
            "rating_version": "v1.0",
            "competition_id": "feb-comp",
        },
        "create_publication": {
            "template_id": "tpl-match-summary-v1",
            "payload_refs": {"match_external_id": "2513600"},
            "scheduled_at": "2026-02-02T08:00:00Z",
        },
        "backfill_season": {"season_code": "2025-2026"},
    }[command_type]


# 1. Full matrix: each role x command. Authorized == not 401/403; the
#    expected outcome is dictated by COMMAND_ROLES, which is the single policy.
MATRIX = {
    "system": [
        "create_or_update_match", "finalize_match", "propose_correction",
        "approve_correction", "register_player_to_squad", "generate_standing_snapshot",
        "generate_leaderboard", "compute_player_rating", "create_publication",
        "backfill_season",
    ],
    "admin": [
        "create_or_update_match", "finalize_match", "propose_correction",
        "approve_correction", "register_player_to_squad", "generate_standing_snapshot",
        "generate_leaderboard", "compute_player_rating", "create_publication",
        "backfill_season",
    ],
    "editor": [
        "create_or_update_match", "finalize_match", "propose_correction",
        "register_player_to_squad", "generate_standing_snapshot",
        "generate_leaderboard", "compute_player_rating",
    ],
}


@pytest.mark.parametrize("role", ["system", "admin", "editor"])
def test_role_matrix_matches_command_roles(client, role):
    allowed = set(MATRIX[role])
    for command_type in MATRIX["system"]:
        resp = client.as_role(role).post(
            f"/v1/commands/{command_type}", json={"payload": _payload(command_type, role)}
        )
        if command_type in allowed:
            assert resp.status_code not in (401, 403), (
                f"{role} should be authorized for {command_type}, got {resp.status_code}"
            )
        else:
            assert resp.status_code == 403, (
                f"{role} must be forbidden for {command_type}, got {resp.status_code}"
            )


def test_anonymous_is_rejected_401_for_every_command(client):
    for command_type in MATRIX["system"]:
        resp = client.anon().post(
            f"/v1/commands/{command_type}", json={"payload": _payload(command_type, "system")}
        )
        assert resp.status_code == 401, f"{command_type} -> {resp.status_code}"


def test_unknown_command_role_not_found_403(client):
    resp = client.as_role("editor").post(
        "/v1/commands/non_existent_command", json={"payload": {}}
    )
    assert resp.status_code == 404


# 2. No client-side escalation, whatever the claim.


def test_envelope_actor_claim_is_rejected_400(client):
    resp = client.post(
        "/v1/commands/create_or_update_match",
        json={"payload": create_payload(), "actor": {"id": "x", "role": "system"}},
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "INVALID_BODY"


def test_payload_system_claim_cannot_escalate_editor(client, db_path):
    """Editor key + approve_correction claiming role=system in approved_by is
    still 403: authorization comes from the principal, never the payload."""
    resp = client.as_role("editor").post(
        "/v1/commands/approve_correction",
        json={"payload": {
            "proposal_id": "00000000-0000-0000-0000-000000000000",
            "approved_by": {"id": "admin-1", "role": "system"},
            "approved_at": "2026-02-02T12:00:00Z",
        }},
    )
    assert resp.status_code == 403


# 3. Fail-closed for bad roles / bad keys / bad contract enums.


def test_unknown_api_key_is_401(client):
    resp = client._client.post(
        "/v1/commands/create_or_update_match",
        json={"payload": create_payload()},
        headers={"Authorization": "Bearer no-such-key"},
    )
    assert resp.status_code == 401


def test_invalid_role_in_config_fails_at_boot():
    with pytest.raises(ValueError):
        ApiKeyAuthenticationProvider.from_env("k=id:viewer")


def test_invalid_role_in_payload_enum_is_422(client):
    resp = client.as_role("admin").post(
        "/v1/commands/approve_correction",
        json={"payload": {
            "proposal_id": "00000000-0000-0000-0000-000000000000",
            "approved_by": {"id": "admin-1", "role": "viewer"},
            "approved_at": "2026-02-02T12:00:00Z",
        }},
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "CONTRACT_VALIDATION"


# Happy paths: the four commands F-01 previously blocked for `system`.


def test_system_approves_correction_end_to_end(client, db_path):
    from uuid import uuid4

    proposal_id = str(uuid4())
    SqliteMatchRepository(SqliteDatabase(db_path)).save(ready_to_finalize())
    assert client.post(
        "/v1/commands/finalize_match",
        json={"payload": {"match_external_id": "2513600"}},
    ).status_code == 200
    propose = client.post(
        "/v1/commands/propose_correction",
        json={"command_id": proposal_id, "payload": {
            "match_external_id": "2513600",
            "proposed_by": {"id": "api", "role": "system"},
            "reason": "official score",
            "changes": [{"op": "update_score", "home_score": 80, "away_score": 77}],
        }},
    )
    assert propose.status_code == 200
    assert propose.json()["events"][0]["event_type"] == "correction_proposed"

    approve = client.post(
        "/v1/commands/approve_correction",
        json={"payload": {
            "proposal_id": proposal_id,
            "approved_by": {"id": "api", "role": "system"},
            "approved_at": "2026-02-02T12:00:00Z",
        }},
    )
    assert approve.status_code == 200, approve.text
    types = [e["event_type"] for e in approve.json()["events"]]
    assert "correction_approved" in types

    proposal = client.get(f"/v1/correction-proposals/{proposal_id}")
    assert proposal.status_code == 200
    assert proposal.json()["status"] == "APPROVED"


def test_system_creates_publication(client):
    resp = client.post("/v1/commands/create_publication", json={
        "payload": {
            "template_id": "tpl-match-summary-v1",
            "payload_refs": {"match_external_id": "2513600"},
            "scheduled_at": "2026-02-02T08:00:00Z",
        },
    })
    assert resp.status_code == 200, resp.text
    assert resp.json()["events"][0]["event_type"] == "publication_created"


def test_system_backfills_season(client):
    resp = client.post("/v1/commands/backfill_season", json={
        "payload": {"season_code": "2025-2026"},
    })
    assert resp.status_code == 200, resp.text
    types = [e["event_type"] for e in resp.json()["events"]]
    assert "season_backfill_started" in types
    assert "season_backfill_completed" in types


def test_system_registers_player_to_squad(client, db_path):
    db = SqliteDatabase(db_path)
    SqlitePlayerRepository(db).save(Player(
        external_id=ExternalId("pl-987"), player_id=PlayerId(str(__import__("uuid").uuid4())), name="Juan"
    ))
    SqliteTeamRepository(db).save(Team(
        external_id=ExternalId("team-123"), team_id=TeamId(str(__import__("uuid").uuid4())), name="Club"
    ))
    resp = client.post("/v1/commands/register_player_to_squad", json={
        "payload": {
            "player_external_id": "pl-987", "team_external_id": "team-123",
            "season_code": "2025-2026", "registered_from": "2025-08-01T00:00:00Z",
        },
    })
    assert resp.status_code == 200, resp.text
    assert resp.json()["events"][0]["event_type"] == "player_registered"
