from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Any

import requests

from .client import FEBMatch


def _team_rows(stats: dict[str, Any]) -> list[dict[str, Any]]:
    boxscore = stats.get("BoxScore") or {}
    rows = boxscore.get("BOXSCORE", {}).get("TEAM", [])
    if rows:
        return rows
    return (stats.get("TeamStats") or {}).get("TEAMSTATS", {}).get("TEAM", [])


def _stable_team_id(team: dict[str, Any], fallback_name: str) -> str:
    raw = str(team.get("id") or fallback_name).strip()
    return raw if raw else f"feb:team:{_slug(fallback_name)}"


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def _minutes(value: Any) -> float:
    if value is None:
        return 0.0
    text = str(value)
    if ":" in text:
        try:
            minutes, seconds = text.split(":", 1)
            return round(int(minutes) + int(seconds) / 60, 2)
        except ValueError:
            return 0.0
    try:
        return float(text)
    except ValueError:
        return 0.0


def _int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _normalized_stats(match: FEBMatch, responses: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    rows = _team_rows(responses)
    if len(rows) < 2:
        return {}, {}

    home = next((row for row in rows if str(row.get("name", "")).strip() == match.home_team_name), rows[0])
    away = next((row for row in rows if str(row.get("name", "")).strip() == match.away_team_name), rows[1])

    def team_payload(team: dict[str, Any], opponent: dict[str, Any]) -> dict[str, Any]:
        return {
            "team_external_id": _stable_team_id(team, str(team.get("name", "team"))),
            "points_for": _int(team.get("pts")),
            "points_against": _int(opponent.get("pts")),
            "field_goals_made": _int(team.get("fgm")),
            "field_goals_attempted": _int(team.get("fga")),
            "three_points_made": _int(team.get("p3m")),
            "three_points_attempted": _int(team.get("p3a")),
            "free_throws_made": _int(team.get("p1m")),
            "free_throws_attempted": _int(team.get("p1a")),
            "turnovers": _int(team.get("to")),
            "rebounds": _int(team.get("rd")) + _int(team.get("ro")),
        }

    return team_payload(home, away), team_payload(away, home)


def _player_payloads(responses: dict[str, Any], scheduled_at: str) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    for team in _team_rows(responses):
        team_id = _stable_team_id(team, str(team.get("name", "team")))
        for player in team.get("PLAYER", []):
            player_id = player.get("id")
            if not player_id:
                continue
            payloads.append(
                {
                    "player_external_id": str(player_id),
                    "team_external_id": team_id,
                    "points": _int(player.get("pts")),
                    "rebounds": _int(player.get("reb")),
                    "assists": _int(player.get("assist")),
                    "steals": _int(player.get("st")),
                    "blocks": _int(player.get("bs")),
                    "turnovers": _int(player.get("to")),
                    "minutes": _minutes(player.get("minFormatted") or player.get("min")),
                    "played_at": scheduled_at,
                }
            )
    return payloads


def build_match_payload(match: FEBMatch, responses: dict[str, Any], *, source_url: str) -> dict[str, Any]:
    team_stats_home, team_stats_away = _normalized_stats(match, responses)
    teams = _team_rows(responses)
    home_id = team_stats_home.get("team_external_id") or f"feb:team:{_slug(match.home_team_name)}"
    away_id = team_stats_away.get("team_external_id") or f"feb:team:{_slug(match.away_team_name)}"

    payload: dict[str, Any] = {
        "external_id": match.external_id,
        "competition_id": "segundafeb",
        "season_code": "2025-2026",
        "round_number": match.round_number,
        "scheduled_at": match.scheduled_at,
        "home_team": {"external_id": home_id, "name": match.home_team_name},
        "away_team": {"external_id": away_id, "name": match.away_team_name},
        "source": {
            "id": f"feb:{match.external_id}",
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        },
        "raw": {
            "match_page_ref": source_url,
            "boxscore_ref": f"{source_url}#BoxScore",
            "teamstats_ref": f"{source_url}#TeamStats",
            "keyfacts_ref": f"{source_url}#KeyFacts",
            "shotchart_ref": f"{source_url}#ShotChart",
            "ranking_ref": f"{source_url}#Ranking",
        },
    }

    if match.home_score is not None and match.away_score is not None:
        payload["score_summary"] = {
            "home_score": match.home_score,
            "away_score": match.away_score,
            "periods": [],
        }
    if team_stats_home and team_stats_away:
        payload["home_team_stats"] = team_stats_home
        payload["away_team_stats"] = team_stats_away
    players = _player_payloads(responses, match.scheduled_at)
    if players:
        payload["player_stats"] = players
    return payload


class ProductionSink:
    def __init__(self, base_url: str, api_key: str, session: requests.Session | None = None, timeout: int = 30):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key.strip()
        self.session = session or requests.Session()
        self.timeout = timeout

    def send_match(self, match: FEBMatch, payload: dict[str, Any]) -> dict[str, Any]:
        command_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"feb-score:{match.external_id}"))
        response = self.session.post(
            f"{self.base_url}/v1/commands/create_or_update_match",
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            json={"command_id": command_id, "payload": payload},
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()

    def finalize_match(self, external_id: str) -> dict[str, Any]:
        command_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"feb-score:finalize:{external_id}"))
        response = self.session.post(
            f"{self.base_url}/v1/commands/finalize_match",
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            json={
                "command_id": command_id,
                "payload": {"match_external_id": external_id, "validation_context": {"strict": False}},
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()
