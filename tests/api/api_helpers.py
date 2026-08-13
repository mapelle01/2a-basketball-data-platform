"""Shared builders and client factory for the FASE 11 HTTP API tests.

Lives in its own module (not conftest.py) so it cannot collide with
``tests/sqlite/conftest.py`` under pytest's prepend import mode.
"""

from datetime import datetime
from uuid import uuid4

from fastapi.testclient import TestClient

from feb_score.api.auth import ApiKeyAuthenticationProvider, Principal
from feb_score.api.main import create_app
from feb_score.domain.match.model import Match
from feb_score.domain.statistics.model import PlayerStats, TeamStats
from feb_score.domain.value_objects import (
    CompetitionId,
    ExternalId,
    MatchId,
    PeriodScore,
    ScoreSummary,
    SeasonCode,
)
from feb_score.infrastructure.logging import RecordingLogger
from feb_score.infrastructure.persistence.connection import SqliteDatabase
from feb_score.infrastructure.wiring import SqliteGateway

# FASE 13 — test API keys. The KEY identifies the principal; the principal owns
# its role. Tests never declare a role in the body (that is the point).
TEST_KEYS = {"system": "system-key", "admin": "admin-key", "editor": "editor-key"}
TEST_PRINCIPALS = {
    "system": Principal(id="api", role="system"),
    "admin": Principal(id="admin-1", role="admin"),
    "editor": Principal(id="editor-1", role="editor"),
}


def auth_header(role: str) -> dict:
    return {"Authorization": f"Bearer {TEST_KEYS[role]}"}


def make_test_auth_provider() -> ApiKeyAuthenticationProvider:
    return ApiKeyAuthenticationProvider(
        {TEST_KEYS[role]: principal for role, principal in TEST_PRINCIPALS.items()}
    )


class AuthedClient:
    """TestClient wrapper that authenticates POST /v1/commands by default.

    General API tests get the ``system`` principal implicitly; security tests use
    ``.anon()`` (no credential) or ``.as_role(...)`` to exercise 401/403 paths.
    """

    def __init__(self, client: TestClient, role: str = "system") -> None:
        self._client = client
        self._role = role

    def __getattr__(self, name):
        return getattr(self._client, name)

    @property
    def app(self):
        return self._client.app

    def post(self, url, *args, **kwargs):
        if url.startswith("/v1/commands/") and "Authorization" not in (kwargs.get("headers") or {}):
            headers = dict(kwargs.pop("headers", {}))
            headers["Authorization"] = f"Bearer {TEST_KEYS[self._role]}"
            kwargs["headers"] = headers
        return self._client.post(url, *args, **kwargs)

    def as_role(self, role: str) -> "AuthedClient":
        return AuthedClient(self._client, role)

    def anon(self) -> TestClient:
        return self._client


def create_payload():
    return {
        "external_id": "2513600",
        "competition_id": "feb-comp",
        "season_code": "2025-2026",
        "round_number": 5,
        "scheduled_at": "2026-02-01T18:30:00Z",
        "home_team": {"external_id": "team-home", "name": "Home"},
        "away_team": {"external_id": "team-away", "name": "Away"},
        "source": {"id": "feb-api", "fetched_at": "2026-02-01T18:00:00Z", "s3_path": "s3://x"},
    }


def ready_to_finalize() -> Match:
    match = Match(
        external_id=ExternalId("2513600"),
        match_id=MatchId(str(uuid4())),
        competition_id=CompetitionId("feb-comp"),
        season_code=SeasonCode("2025-2026"),
        round_number=5,
        home_team_id=ExternalId("team-home"),
        away_team_id=ExternalId("team-away"),
        scheduled_at=datetime(2026, 2, 1, 18, 30),
    )
    match.score_summary = ScoreSummary(
        home_score=80,
        away_score=77,
        periods=(PeriodScore(period=1, home=40, away=38), PeriodScore(period=2, home=40, away=39)),
    )
    match.home_team_stats = TeamStats(
        team_external_id="team-home", points_for=80, points_against=77,
        field_goals_made=30, field_goals_attempted=60, three_points_made=8,
        three_points_attempted=20, free_throws_made=12, free_throws_attempted=16,
        turnovers=10, rebounds=38,
    )
    match.away_team_stats = TeamStats(
        team_external_id="team-away", points_for=77, points_against=80,
        field_goals_made=28, field_goals_attempted=62, three_points_made=7,
        three_points_attempted=18, free_throws_made=14, free_throws_attempted=18,
        turnovers=12, rebounds=34,
    )
    match.player_stats = (
        PlayerStats(player_external_id="pl-1", team_external_id="team-home", points=22,
                    rebounds=9, assists=5, turnovers=2),
    )
    return match


def make_client(db_path: str, **gateway_kwargs) -> AuthedClient:
    db = SqliteDatabase(db_path)
    db.migrate()
    gateway = SqliteGateway(db, logger=RecordingLogger(), **gateway_kwargs)
    app = create_app(gateway, logger=RecordingLogger(), auth=make_test_auth_provider())
    return AuthedClient(TestClient(app))