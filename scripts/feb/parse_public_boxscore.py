#!/usr/bin/env python3
"""Parse the FEB public match page (``Partido.aspx``) into a full boxscore.

Public, tokenless, server-rendered — the companion to ``discover_matches.py``
(which scrapes the public calendar). This page carries the COMPLETE per-player
boxscore in clean CSS classes back to ~2002: points, assists, rebounds
(off/def/total), steals, blocks, turnovers, minutes, fouls, dunks, the four
shooting splits (T2/T3/TC/TL as made/attempted), the official ``valoración``
(FEB VAL) and the ``balance`` (+/-), plus per-quarter scores. It therefore feeds
BOTH the historical backfill and the per-player shooting lane without needing
the LiveStats API token.

Design: pure parsing (no network in ``parse_public_boxscore``); ``fetch_match_page``
is a thin optional helper for the backfill runner. Player links are
``Jugador.aspx?i=<team_external_id>&c=<player_external_id>`` — so each row carries
both ids and player→team association never depends on table position.
"""
from __future__ import annotations

import html as _html
import re
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

DEFAULT_PUBLIC_MATCH_BASE = "https://baloncestoenvivo.feb.es/Partido.aspx"
USER_AGENT = "feb-score-boxscore/1.0"
TIMEOUT_SECONDS = 30


class ParseError(RuntimeError):
    """Raised when the page is not a parseable FEB boxscore."""


class SourceError(RuntimeError):
    """Raised when the public page cannot be fetched."""


@dataclass(frozen=True)
class Shot:
    made: int
    attempted: int

    @property
    def pct(self) -> Optional[float]:
        return round(100.0 * self.made / self.attempted, 1) if self.attempted else None


@dataclass(frozen=True)
class PublicPlayerLine:
    player_external_id: str        # c=  in Jugador.aspx
    team_external_id: str          # i=  in Jugador.aspx (== scoreboard team id)
    name: str                      # "APELLIDOS, NOMBRE"
    starter: bool
    dorsal: Optional[int]
    minutes: float                 # decimal minutes from MM:SS
    points: int
    assists: int
    rebounds_offensive: int
    rebounds_defensive: int
    rebounds_total: int
    steals: int
    blocks: int
    turnovers: int
    fouls_committed: int
    fouls_received: int
    dunks: int
    valoracion: int                # official FEB VAL
    plus_minus: int                # balance
    field_goals: Shot              # tiros campo (TC)
    two_points: Shot               # tiros dos (T2)
    three_points: Shot             # tiros tres (T3)
    free_throws: Shot              # tiros libres (TL)


@dataclass(frozen=True)
class PublicTeam:
    external_id: str
    name: str
    score: int
    quarters: Tuple[int, ...]


@dataclass(frozen=True)
class PublicBoxscore:
    match_external_id: str
    home: PublicTeam
    away: PublicTeam
    players: Tuple[PublicPlayerLine, ...]

    def players_of(self, team_external_id: str) -> Tuple[PublicPlayerLine, ...]:
        return tuple(p for p in self.players if p.team_external_id == team_external_id)


# ---------------------------------------------------------------------------
# Cell helpers
# ---------------------------------------------------------------------------

_TAG_RE = re.compile(r"<[^>]+>")
_SPAN_PCT_RE = re.compile(r"<span[^>]*porcentaje[^>]*>.*?</span>", re.S)


def _text(fragment: str) -> str:
    """Strip tags + unescape entities + collapse whitespace."""
    return _html.unescape(_TAG_RE.sub("", fragment)).replace("\xa0", " ").strip()


def _int(fragment: str) -> int:
    t = _text(fragment)
    m = re.search(r"-?\d+", t)
    return int(m.group(0)) if m else 0


def _minutes(fragment: str) -> float:
    """'22:50' -> 22.8 (decimal minutes). Empty / '-' -> 0.0."""
    t = _text(fragment)
    m = re.match(r"(\d+):(\d{1,2})", t)
    if m:
        return round(int(m.group(1)) + int(m.group(2)) / 60.0, 1)
    return float(_int(t)) if re.search(r"\d", t) else 0.0


def _shot(fragment: str) -> Shot:
    """'2/5 <span>40%</span>' -> Shot(2, 5). Missing -> Shot(0, 0)."""
    t = _SPAN_PCT_RE.sub("", fragment)
    m = re.search(r"(\d+)\s*/\s*(\d+)", _text(t))
    return Shot(int(m.group(1)), int(m.group(2))) if m else Shot(0, 0)


def _td(row: str, cls: str) -> str:
    """Inner HTML of ``<td class="cls">…</td>`` (exact class), or '' if absent."""
    m = re.search(rf'<td class="{re.escape(cls)}"[^>]*>(.*?)</td>', row, re.S)
    return m.group(1) if m else ""


# ---------------------------------------------------------------------------
# Scoreboard + quarters
# ---------------------------------------------------------------------------

# The two scoreboard columns are MIRRORED (home: name then score; away: score
# then name), so extract id/name/score from each column block order-independently.
_EQUIPO_ID_RE = re.compile(r"Equipo\.aspx\?i=(\d+)")
_NOMBRE_RE = re.compile(r'Nombre">([^<]+)</span>')
_RESULTADO_RE = re.compile(r'class="resultado"[^>]*>\s*(\d+)')
_PARCIAL_BLOCK_RE = re.compile(r'fila parciales.*?(?=<div class="fila\b|</div>\s*</div>\s*</div>)', re.S)
_PARCIAL_TEAM_RE = re.compile(
    r'columna equipo (local|visitante)[^>]*>(.*?)(?=<div class="columna|\Z)', re.S
)


def _quarters(html: str) -> dict:
    block_m = _PARCIAL_BLOCK_RE.search(html)
    out = {"local": (), "visitante": ()}
    if not block_m:
        return out
    block = block_m.group(0)
    for side, inner in _PARCIAL_TEAM_RE.findall(block):
        nums = tuple(int(x) for x in re.findall(r"<span>\s*(\d+)\s*</span>", inner))
        out[side] = nums
    return out


# ---------------------------------------------------------------------------
# Players
# ---------------------------------------------------------------------------

_ROW_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S)
_PLAYER_LINK_RE = re.compile(
    r'Jugador\.aspx\?i=(\d+)&(?:amp;)?c=(\d+)"[^>]*>(.*?)</a>', re.S
)


def _player_line(row: str) -> Optional[PublicPlayerLine]:
    link = _PLAYER_LINK_RE.search(row)
    if not link:  # header / totals / non-player row
        return None
    team_id, player_id, name = link.group(1), link.group(2), _text(link.group(3))
    return PublicPlayerLine(
        player_external_id=player_id,
        team_external_id=team_id,
        name=name,
        starter=bool(_text(_td(row, "inicial"))),
        dorsal=(_int(_td(row, "dorsal")) or None),
        minutes=_minutes(_td(row, "minutos")),
        points=_int(_td(row, "puntos")),
        assists=_int(_td(row, "asistencias")),
        rebounds_offensive=_int(_td(row, "rebotes ofensivos")),
        rebounds_defensive=_int(_td(row, "rebotes defensivos")),
        rebounds_total=_int(_td(row, "rebotes total")),
        steals=_int(_td(row, "recuperaciones")),
        blocks=_int(_td(row, "tapones favor")),
        turnovers=_int(_td(row, "perdidas")),
        fouls_committed=_int(_td(row, "faltas cometidas")),
        fouls_received=_int(_td(row, "faltas recibidas")),
        dunks=_int(_td(row, "mates")),
        valoracion=_int(_td(row, "valoracion")),
        plus_minus=_int(_td(row, "balance")),
        field_goals=_shot(_td(row, "tiros campo")),
        two_points=_shot(_td(row, "tiros dos")),
        three_points=_shot(_td(row, "tiros tres")),
        free_throws=_shot(_td(row, "tiros libres")),
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def _parse_team(html: str, side: str, quarters: Tuple[int, ...]) -> PublicTeam:
    start = html.find(f'columna equipo {side}"')
    if start < 0:
        raise ParseError(f"scoreboard column '{side}' not found")
    nxt = html.find('class="columna', start + 12)
    block = html[start: nxt if nxt > 0 else start + 800]
    eid = _EQUIPO_ID_RE.search(block)
    name = _NOMBRE_RE.search(block)
    score = _RESULTADO_RE.search(block)
    if not (eid and name and score):
        raise ParseError(f"scoreboard '{side}' missing id/name/score")
    return PublicTeam(external_id=eid.group(1), name=_text(name.group(1)),
                      score=int(score.group(1)), quarters=quarters)


def parse_public_boxscore(html: str, match_external_id: str = "") -> PublicBoxscore:
    """Parse a ``Partido.aspx`` page into a :class:`PublicBoxscore`.

    Raises :class:`ParseError` if the two teams or the player boxscore can't be
    found (e.g. a match with no published stats)."""
    q = _quarters(html)
    home = _parse_team(html, "local", q.get("local", ()))
    away = _parse_team(html, "visitante", q.get("visitante", ()))

    players: List[PublicPlayerLine] = []
    for row in _ROW_RE.findall(html):
        line = _player_line(row)
        if line is not None:
            players.append(line)
    if not players:
        raise ParseError("no player rows with a Jugador.aspx link")

    return PublicBoxscore(match_external_id=match_external_id, home=home, away=away,
                          players=tuple(players))


# ---------------------------------------------------------------------------
# Mapper: PublicBoxscore -> upsert_match_stats command
# ---------------------------------------------------------------------------
# Mirrors scripts/feb/ingest_match.py's stats command shape (contract
# commands/upsert_match_stats.v1.json), so a scraped boxscore ingests exactly
# like a LiveStats one — but carrying per-player shooting/fouls/+/-. The command
# id reuses the same UUIDv5 scheme, so public-HTML and LiveStats ingestion of the
# same match are idempotent against each other.

_COMMAND_VERSION = "1.0"
_ACTOR = {"id": "ingestor-1", "role": "system"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stats_command_id(season_code: str, competition_id: str, external_id: str) -> str:
    name = f"{season_code}|{competition_id}|{external_id}"
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"feb-score-ingestor-stats:{name}"))


def _team_stats_payload(team: PublicTeam, opponent_score: int,
                        players: Tuple[PublicPlayerLine, ...]) -> Dict[str, Any]:
    return {
        "team_external_id": team.external_id,
        "points_for": team.score,
        "points_against": opponent_score,
        "field_goals_made": sum(p.field_goals.made for p in players),
        "field_goals_attempted": sum(p.field_goals.attempted for p in players),
        "three_points_made": sum(p.three_points.made for p in players),
        "three_points_attempted": sum(p.three_points.attempted for p in players),
        "free_throws_made": sum(p.free_throws.made for p in players),
        "free_throws_attempted": sum(p.free_throws.attempted for p in players),
        "turnovers": sum(p.turnovers for p in players),
        "rebounds": sum(p.rebounds_total for p in players),
    }


def _player_stats_payload(p: PublicPlayerLine, played_at: Optional[str]) -> Dict[str, Any]:
    return {
        "player_external_id": p.player_external_id,
        "team_external_id": p.team_external_id,
        "points": p.points,
        "rebounds": p.rebounds_total,
        "assists": p.assists,
        "steals": p.steals,
        "blocks": p.blocks,
        "turnovers": p.turnovers,
        "minutes": p.minutes,
        "played_at": played_at,
        "field_goals_made": p.field_goals.made,
        "field_goals_attempted": p.field_goals.attempted,
        "three_points_made": p.three_points.made,
        "three_points_attempted": p.three_points.attempted,
        "free_throws_made": p.free_throws.made,
        "free_throws_attempted": p.free_throws.attempted,
        "fouls": p.fouls_committed,
        "plus_minus": p.plus_minus,
    }


def to_stats_command(box: PublicBoxscore, season_code: str, competition_id: str,
                     played_at: Optional[str] = None,
                     issued_at: Optional[str] = None) -> Dict[str, Any]:
    """Build the ``upsert_match_stats`` command envelope from a public boxscore.

    Team totals are aggregated from the player rows (+ the scoreboard scores).
    ``played_at`` (ISO, from the calendar) flows to each player row; ``None`` is
    valid per the contract. Idempotent via the shared stats command id."""
    home_p = box.players_of(box.home.external_id)
    away_p = box.players_of(box.away.external_id)
    return {
        "command_id": _stats_command_id(season_code, competition_id, box.match_external_id),
        "meta": {"version": _COMMAND_VERSION, "issued_at": issued_at or _now_iso()},
        "actor": dict(_ACTOR),
        "payload": {
            "match_external_id": box.match_external_id,
            "season_code": season_code,
            "home_team_stats": _team_stats_payload(box.home, box.away.score, home_p),
            "away_team_stats": _team_stats_payload(box.away, box.home.score, away_p),
            "player_stats": [_player_stats_payload(p, played_at) for p in box.players],
        },
    }


def fetch_match_page(match_external_id: str, base_url: str = DEFAULT_PUBLIC_MATCH_BASE) -> str:
    """GET the public match page (no token, no POST). For the backfill runner."""
    url = f"{base_url}?p={match_external_id}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:  # noqa: S310 (public FEB page)
            if not (200 <= resp.status < 300):
                raise SourceError(f"FEB {url} HTTP {resp.status}")
            return resp.read().decode("utf-8", "replace")
    except SourceError:
        raise
    except (urllib.error.URLError, urllib.error.HTTPError, OSError) as exc:
        raise SourceError(f"FEB {url} fetch failed: {exc}") from exc


if __name__ == "__main__":  # manual smoke: python3 parse_public_boxscore.py <match_id>
    import sys
    box = parse_public_boxscore(fetch_match_page(sys.argv[1]), sys.argv[1])
    print(f"{box.home.name} {box.home.score} - {box.away.score} {box.away.name}")
    print(f"quarters: {box.home.quarters} vs {box.away.quarters} · {len(box.players)} players")
    for p in box.players[:3]:
        print(f"  {p.name}: {p.points}p {p.rebounds_total}r {p.assists}a "
              f"T3 {p.three_points.made}/{p.three_points.attempted} VAL {p.valoracion} +/- {p.plus_minus}")
