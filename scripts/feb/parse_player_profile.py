#!/usr/bin/env python3
"""Parse the FEB public player profile (``Jugador.aspx``) into a bio.

Public and tokenless, like the boxscore parser — and reached from the very link
the boxscore already gives us: ``Jugador.aspx?i=<team_external_id>&c=<player_external_id>``.
The page carries what a match boxscore never does: position, height, birth date
(sometimes with the birth city) and nationality.

Measured coverage on a full real 21-player roster: nationality 21/21, height
21/21, birth date 21/21, position 20/21. WEIGHT is never published (always
"- Kg"), so it is not parsed. Some profiles are entirely blank, so every field
is Optional and a blank page yields an empty bio rather than an error.

Markup: ``<div class="nodo"><span class="label">FIELD</span><span class="string">VALUE</span></div>``.
NOTE the label span sometimes carries an id attribute (Nacionalidad does), so
the pattern must allow attributes on BOTH spans.

Design: pure parsing (no network in ``parse_player_profile``); ``fetch_player_page``
is a thin optional helper for the backfill.
"""
from __future__ import annotations

import html as _html
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import date
from typing import Optional

DEFAULT_PUBLIC_PLAYER_BASE = "https://baloncestoenvivo.feb.es/Jugador.aspx"
USER_AGENT = "feb-score-bio/1.0"
TIMEOUT_SECONDS = 30


class SourceError(RuntimeError):
    """Raised when the public profile cannot be fetched."""


@dataclass(frozen=True)
class PlayerBio:
    player_external_id: str
    name: Optional[str] = None
    position: Optional[str] = None       # Base / Escolta / Alero / A-Pivot / Pivot
    height_cm: Optional[int] = None
    birth_date: Optional[date] = None
    birth_place: Optional[str] = None    # only when the page appends a city
    nationality: Optional[str] = None    # uppercase country, e.g. "ESPAÑA"

    @property
    def is_empty(self) -> bool:
        return not any((self.position, self.height_cm, self.birth_date,
                        self.birth_place, self.nationality))


_TAG_RE = re.compile(r"<[^>]+>")
# Both spans may carry attributes (the Nacionalidad label has an id=).
_FIELD_RE = re.compile(
    r'<span[^>]*class="label"[^>]*>(.*?)</span>\s*'
    r'<span[^>]*class="string"[^>]*>(.*?)</span>',
    re.S,
)
_HEIGHT_RE = re.compile(r"(\d{2,3})\s*cm", re.I)
_DATE_RE = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{4})")
_NAME_RE = re.compile(r'<div class="nombre">(.*?)</div>', re.S)


def _clean(fragment: str) -> str:
    return _html.unescape(_TAG_RE.sub("", fragment)).replace("\xa0", " ").strip()


def _fields(html: str) -> dict:
    return {_clean(k): _clean(v) for k, v in _FIELD_RE.findall(html)}


def _height(value: str) -> Optional[int]:
    m = _HEIGHT_RE.search(value or "")
    return int(m.group(1)) if m else None


def _birth(value: str) -> tuple:
    """'11/04/1998 Barcelona' -> (date(1998,4,11), 'Barcelona')."""
    if not value:
        return None, None
    m = _DATE_RE.search(value)
    born = None
    if m:
        try:
            born = date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        except ValueError:
            born = None
    place = _DATE_RE.sub("", value).strip(" ,;") or None
    return born, place


def _text_or_none(value: Optional[str]) -> Optional[str]:
    v = (value or "").strip()
    return v or None


def parse_player_profile(html: str, player_external_id: str = "") -> PlayerBio:
    """Parse a ``Jugador.aspx`` page into a :class:`PlayerBio`.

    Never raises on a blank or partial profile: missing fields stay ``None``
    (FEB publishes some profiles empty), so the caller can persist what exists
    and leave the rest untouched instead of inventing values.
    """
    f = _fields(html)
    born, place = _birth(f.get("Fecha Nacimiento", ""))
    # Strictly the contents of the name div: on a blank profile it is EMPTY, and
    # a looser pattern walks on and picks up the team name that follows it.
    name = _NAME_RE.search(html)
    return PlayerBio(
        player_external_id=player_external_id,
        name=_text_or_none(_clean(name.group(1)) if name else None),
        position=_text_or_none(f.get("Puesto")),
        height_cm=_height(f.get("Altura", "")),
        birth_date=born,
        birth_place=place,
        nationality=_text_or_none(f.get("Nacionalidad")),
    )


def fetch_player_page(player_external_id: str, team_external_id: str,
                      base_url: str = DEFAULT_PUBLIC_PLAYER_BASE) -> str:
    """Fetch a public profile. Public page: no token, no credentials."""
    url = f"{base_url}?i={team_external_id}&c={player_external_id}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:  # noqa: S310
            if not (200 <= resp.status < 300):
                raise SourceError(f"FEB player page HTTP {resp.status}")
            return resp.read().decode("utf-8", "replace")
    except SourceError:
        raise
    except (urllib.error.URLError, urllib.error.HTTPError, OSError) as exc:
        raise SourceError(f"FEB player page fetch failed: {exc}") from exc
