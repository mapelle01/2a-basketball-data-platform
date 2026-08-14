from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup


BASE_URL = "https://baloncestoenvivo.feb.es"
LIVE_STATS_BASE = "https://intrafeb.feb.es/LiveStats.API/api/v1"
DEFAULT_RESULTS_URL = f"{BASE_URL}/resultados.aspx?g=2&t=2025&nm=segundafeb"
DEFAULT_SEASON_CODE = "2025-2026"


@dataclass(frozen=True)
class FEBMatch:
    external_id: str
    match_url: str
    home_team_name: str
    away_team_name: str
    home_score: int | None
    away_score: int | None
    scheduled_at: str
    round_number: int
    status: str


class FEBClient:
    """Read-only client for the public FEB competition pages and LiveStats API.

    The LiveStats API is not called with a permanent credential. FEB embeds a
    short-lived token in each match page; the connector extracts it and uses it
    only for the subsequent read-only LiveStats requests.
    """

    def __init__(self, session: requests.Session | None = None, timeout: int = 30):
        self.session = session or requests.Session()
        self.timeout = timeout
        self.session.headers.update(
            {"User-Agent": "feb-score-source-connector/1.0", "Accept-Language": "es-ES,es;q=0.9"}
        )

    def fetch_results_page(self, url: str = DEFAULT_RESULTS_URL) -> str:
        response = self.session.get(url, timeout=self.timeout)
        response.raise_for_status()
        return response.text

    def list_matches(self, html: str) -> list[FEBMatch]:
        soup = BeautifulSoup(html, "lxml")
        round_number = self._parse_round_number(soup)
        matches: list[FEBMatch] = []

        for row in soup.find_all("tr"):
            cells = row.find_all(["td", "th"])
            if len(cells) < 4:
                continue
            score_link = cells[1].find("a", href=True)
            if score_link is None:
                continue

            match_id = self._match_id(score_link["href"])
            if match_id is None:
                continue

            home, away = self._split_teams(cells[0].get_text(" ", strip=True))
            home_score, away_score = self._parse_score(cells[1].get_text(" ", strip=True))
            scheduled_at = self._parse_datetime(
                cells[2].get_text(" ", strip=True), cells[3].get_text(" ", strip=True)
            )
            if scheduled_at is None:
                continue

            matches.append(
                FEBMatch(
                    external_id=str(match_id),
                    match_url=urljoin(BASE_URL, score_link["href"]),
                    home_team_name=home,
                    away_team_name=away,
                    home_score=home_score,
                    away_score=away_score,
                    scheduled_at=scheduled_at,
                    round_number=round_number,
                    status="FINALIZED" if home_score is not None and away_score is not None else "SCHEDULED",
                )
            )
        return matches

    def fetch_match_page(self, match: FEBMatch) -> str:
        response = self.session.get(match.match_url, timeout=self.timeout)
        response.raise_for_status()
        return response.text

    def fetch_live_stats(self, match: FEBMatch, match_html: str) -> dict[str, Any]:
        token = self._extract_token(match_html)
        if not token:
            raise RuntimeError(f"FEB token not found for match {match.external_id}")

        referer = match.match_url
        headers = {"Authorization": f"Bearer {token}", "Referer": referer, "Accept": "application/json"}
        responses: dict[str, Any] = {}
        for endpoint in ("BoxScore", "TeamStats", "KeyFacts", "ShotChart", "Ranking"):
            url = f"{LIVE_STATS_BASE}/{endpoint}/{match.external_id}"
            response = self.session.get(url, headers=headers, timeout=self.timeout)
            response.raise_for_status()
            responses[endpoint] = response.json()
        return responses

    @staticmethod
    def _extract_token(html: str) -> str | None:
        soup = BeautifulSoup(html, "lxml")
        field = soup.select_one("#contentToken input")
        return field.get("value") if field else None

    @staticmethod
    def _match_id(href: str) -> int | None:
        match = re.search(r"[?&]p=(\d+)", href)
        if match:
            return int(match.group(1))
        match = re.search(r"/partido/(\d+)", href, re.IGNORECASE)
        return int(match.group(1)) if match else None

    @staticmethod
    def _parse_round_number(soup: BeautifulSoup) -> int:
        text = soup.get_text(" ", strip=True)
        match = re.search(r"Resultados\s+Jornada\s+(\d+)", text, re.IGNORECASE)
        return int(match.group(1)) if match else 0

    @staticmethod
    def _split_teams(text: str) -> tuple[str, str]:
        parts = re.split(r"\s+-\s+", text, maxsplit=1)
        return (parts[0].strip(), parts[1].strip()) if len(parts) == 2 else (text.strip(), "")

    @staticmethod
    def _parse_score(text: str) -> tuple[int | None, int | None]:
        if text.strip() in {"*-*", "--", "x-x"}:
            return None, None
        match = re.match(r"^\s*(\d+)\s*-\s*(\d+)\s*$", text)
        return (int(match.group(1)), int(match.group(2))) if match else (None, None)

    @staticmethod
    def _parse_datetime(date_text: str, time_text: str) -> str | None:
        try:
            dt = datetime.strptime(f"{date_text} {time_text or '00:00'}", "%d/%m/%Y %H:%M")
        except ValueError:
            return None
        return dt.isoformat(timespec="seconds")
