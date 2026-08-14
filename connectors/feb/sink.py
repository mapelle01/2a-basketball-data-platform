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


def build_match_payload(match: FEBMatch, responses: dict[str, Any], *, source_url: str) -> dict[str, Any]:
    """Map FEB data to the current v1 create/update contract.

    The current Match contract persists source references. LiveStats payloads are
    intentionally not serialized into the command until a dedicated statistics
    ingestion contract is introduced, preventing silent data loss.
    """
    teams = _team_rows(responses)
    home_id = next(
        (_stable_team_id(t, match.home_team_name) for t in teams if str(t.get("name", "")).strip() == match.home_team_name),
        f"feb:team:{_slug(match.home_team_name)}",
    )
    away_id = next(
        (_stable_team_id(t, match.away_team_name) for t in teams if str(t.get("name", "")).strip() == match.away_team_name),
        f"feb:team:{_slug(match.away_team_name)}",
    )

    return {
        "external_id": match.external_id,
        "competition_id": "segundafeb",
        "season_code": "2025-2026",
        "round_number": match.round_number or 1,
        "scheduled_at": match.scheduled_at,
        "home_team": {"external_id": home_id, "name": match.home_team_name},
        "away_team": {"external_id": away_id, "name": match.away_team_name},
        "source": {"id": f"feb:{match.external_id}", "fetched_at": datetime.now(timezone.utc).isoformat()},
        "raw": {
            "match_page_ref": source_url,
            "boxscore_ref": f"{source_url}#BoxScore",
            "teamstats_ref": f"{source_url}#TeamStats",
            "keyfacts_ref": f"{source_url}#KeyFacts",
            "shotchart_ref": f"{source_url}#ShotChart",
            "ranking_ref": f"{source_url}#Ranking",
        },
    }


class ProductionSink:
    def __init__(self, base_url: str, api_key: str, session: requests.Session | None = None, timeout: int = 30):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key.strip()
        if not self.api_key:
            raise ValueError("api_key must not be empty")
        self.session = session or requests.Session()
        self.timeout = timeout

    def send_match(self, match: FEBMatch, payload: dict[str, Any]) -> dict[str, Any]:
        command_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"feb-score:create-or-update:{match.external_id}"))
        response = self.session.post(
            f"{self.base_url}/v1/commands/create_or_update_match",
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            json={"command_id": command_id, "payload": payload},
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()
