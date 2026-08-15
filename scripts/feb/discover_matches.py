#!/usr/bin/env python3
"""FASE 22.1 — Match Discovery (Segunda FEB 2025-2026).

Descubre los partidos de una jornada de Segunda FEB desde la fuente pública
oficial de FEB (`baloncestoenvivo.feb.es/calendario.aspx`) SIN postbacks ASP.NET,
sin POSTs y sin tocar la API ni Production.

Fuente (GET único):
    https://baloncestoenvivo.feb.es/calendario.aspx?g=2&t=2025&nm=segundafeb

El calendario publica la temporada completa del grupo seleccionado (por defecto
"Liga Regular ESTE", 7 partidos/jornada) en una sola página, sin navegación por
postback (a diferencia de `resultados.aspx`, que requiere `__doPostBack` para
cambiar de jornada). El grupo OESTE no es alcanzable por URL GET (dropdown
ASP.NET) -> queda fuera del alcance de FASE 22.1 y se documenta como trabajo futuro.

Decisiones de diseño (confirmadas):
  * `scheduled_at` = fecha de la jornada (del `<h1>`) a medianoche con offset
    `+01:00` (misma política TZ provisional que FASE 21.B2). El calendario NO
    publica la hora individual de cada partido; la hora exacta la completa la
    ingesta (BoxScore `starttime`) en fases posteriores.
  * `external_id` = match_id FEB (de `Partido.aspx?p=<id>`).
  * `round_number` = número de jornada (1..26, "Jornada N DD/MM/YYYY").
  * dedupe por `external_id`; orden determinista por `external_id`.
  * filas inválidas (sin `Partido.aspx` o sin equipo local/visitante) se ignoran
    sin abortar la jornada.

Solo stdlib (urllib + html/re): el venv no dispone de requests/bs4/lxml.
No imprime secretos (no usa ninguno) y no POSTea.

Exit codes (CLI):
    2  configuración inválida (season no soportada, argumentos inválidos)
    3  error de fuente (fetch falla o página sin jornadas parseables)
    6  error inesperado
"""
from __future__ import annotations

import argparse
import html
import os
import re
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Dict, List, Optional

DEFAULT_DISCOVERY_BASE = "https://baloncestoenvivo.feb.es/calendario.aspx"
COMP_ID = 2
COMP_CODE = "segundafeb"
SEASON_T = "2025"  # FEB usa el año de inicio: t=2025 -> temporada 2025-2026
SUPPORTED_SEASON = "2025-2026"
TZ_OFFSET = "+01:00"  # provisional, igual que FASE 21.B2
USER_AGENT = "feb-score-discover/1.0"
TIMEOUT_SECONDS = 30

_H1_JORNADA_RE = re.compile(
    r"<h1[^>]*>\s*Jornada\s+(\d+)\s+(\d{2}/\d{2}/\d{4})\s*</h1>", re.I
)
_TR_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S)
_PARTIDO_RE = re.compile(r"Partido\.aspx\?p=(\d+)")
_EQUIPO_RE = re.compile(r'class="equipo (local|visitante)".*?Equipo\.aspx\?i=\d+"[^>]*>([^<]+)</a>', re.S)


class ConfigError(RuntimeError):
    """Configuración inválida (temporada no soportada, round inválido) -> exit 2."""


class SourceError(RuntimeError):
    """Error de fuente (fetch/parse del calendario de FEB) -> exit 3."""


@dataclass(frozen=True)
class MatchRef:
    external_id: int
    round_number: int
    scheduled_at: str
    home_team: str
    away_team: str
    source_url: str


def _env(name: str, default: Optional[str] = None) -> Optional[str]:
    v = os.environ.get(name, "").strip()
    if not v:
        return default
    return v


def _discovery_url(season_code: str) -> str:
    """URL GET del calendario para la temporada soportada (sin postbacks)."""
    if season_code != SUPPORTED_SEASON:
        raise ConfigError(
            f"unsupported season {season_code!r}; only {SUPPORTED_SEASON!r}"
        )
    base = _env("FEB_DISCOVERY_BASE_URL", DEFAULT_DISCOVERY_BASE) or DEFAULT_DISCOVERY_BASE
    return f"{base}?g={COMP_ID}&t={SEASON_T}&nm={COMP_CODE}"


def fetch_calendar(url: str) -> str:
    """GET del calendario (no secrets, no POST). Lanza SourceError en fallo."""
    req = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "text/html"},
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:  # noqa: S310 (configurable, fuente FEB pública)
            if not (200 <= resp.status < 300):
                raise SourceError(f"FEB {url} HTTP {resp.status}")
            return resp.read().decode("utf-8", "replace")
    except SourceError:
        raise
    except (urllib.error.URLError, urllib.error.HTTPError, OSError) as exc:
        raise SourceError(f"FEB {url} fetch failed: {exc}") from exc


def _scheduled_at(date_dmy: str) -> str:
    """`04/10/2025` -> `2025-10-04T00:00:00+01:00` (hora no publicada por la fuente)."""
    dd, mm, yyyy = date_dmy.split("/")
    return f"{yyyy}-{mm}-{dd}T00:00:00{TZ_OFFSET}"


def _parse_row(tr: str, round_number: int, scheduled_at: str) -> Optional[MatchRef]:
    """Fila `<tr>` del calendario -> MatchRef, o None si es inválida.

    Fila válida: enlace `Partido.aspx?p=<id>` + equipo local + equipo visitante.
    Se ignoran (None) las filas sin partido, sin equipos, o con equipos vacíos.
    """
    m = _PARTIDO_RE.search(tr)
    if not m:
        return None
    ext = int(m.group(1))

    local = _EQUIPO_RE.search(tr)
    if not local:
        return None
    # Primer match = local, segundo = visitante (orden del HTML).
    visit = _EQUIPO_RE.search(tr, local.end())
    if not visit:
        return None

    home = html.unescape(local.group(2).strip())
    away = html.unescape(visit.group(2).strip())
    if not home or not away:
        return None

    return MatchRef(
        external_id=ext,
        round_number=round_number,
        scheduled_at=scheduled_at,
        home_team=home,
        away_team=away,
        source_url=f"https://baloncestoenvivo.feb.es/Partido.aspx?p={ext}",
    )


def parse_calendar(html_text: str) -> Dict[int, List[MatchRef]]:
    """`calendario.aspx` HTML -> {round_number: [MatchRef]} (dedupe por external_id).

    Divide por los `<h1 class="titulo-modulo">Jornada N DD/MM/YYYY</h1>`; cada
    sección (hasta la siguiente jornada) contiene la tabla con los partidos.
    Filas inválidas se omiten; IDs duplicados se deduplican conservando el primero.
    """
    headers = list(_H1_JORNADA_RE.finditer(html_text))
    by_round: Dict[int, List[MatchRef]] = {}
    for idx, m in enumerate(headers):
        round_number = int(m.group(1))
        scheduled_at = _scheduled_at(m.group(2))
        start = m.end()
        end = headers[idx + 1].start() if idx + 1 < len(headers) else len(html_text)
        section = html_text[start:end]

        refs: List[MatchRef] = []
        seen: set = set()
        for tr in _TR_RE.findall(section):
            ref = _parse_row(tr, round_number, scheduled_at)
            if ref is None or ref.external_id in seen:
                continue
            seen.add(ref.external_id)
            refs.append(ref)
        if refs:
            by_round[round_number] = refs
    return by_round


def discover_matches(
    season_code: str,
    round_number: int,
    calendar_html: Optional[str] = None,
) -> List[MatchRef]:
    """Descubre los partidos de una jornada de Segunda FEB 2025-2026.

    Args:
        season_code: solo `2025-2026` (config inválida -> SystemExit 2).
        round_number: número de jornada (>= 1; invalid -> SystemExit 2).
        calendar_html: HTML del calendario (offline/tests). Si es None se hace
            el GET real a la fuente FEB.

    Returns:
        Lista de MatchRef de la jornada pedida (vací= si la jornada no existe),
        ordenada por `external_id`. Sin POSTs, sin production, sin secrets.
    """
    if season_code != SUPPORTED_SEASON:
        raise ConfigError(
            f"unsupported season {season_code!r}; only {SUPPORTED_SEASON!r}"
        )
    if not isinstance(round_number, int) or isinstance(round_number, bool) or round_number < 1:
        raise ConfigError(
            f"invalid round {round_number!r}; expected integer >= 1"
        )

    if calendar_html is None:
        url = _discovery_url(season_code)
        calendar_html = fetch_calendar(url)

    by_round = parse_calendar(calendar_html)
    if not by_round:
        raise SourceError("no jornadas parsed from calendar HTML")

    refs = list(dict.fromkeys(by_round.get(round_number, [])))
    refs.sort(key=lambda r: r.external_id)
    return refs


def resolve_round_for_match(
    season_code: str,
    external_id: str,
    calendar_html: Optional[str] = None,
) -> Optional[int]:
    """Jornada real de un match dado (para `--match-id` manual, FASE 22.4).

    Hace UN GET al calendario (o acepta HTML offline) y busca el `external_id`;
    devuelve su round_number o None si el partido no está en el calendario.
    Coherente con el pipeline: la jornada SIEMPRE viene del discovery (nunca se
    inventa). Lanza ConfigError/SourceError igual que discover_matches().
    """
    if season_code != SUPPORTED_SEASON:
        raise ConfigError(
            f"unsupported season {season_code!r}; only {SUPPORTED_SEASON!r}"
        )
    if calendar_html is None:
        url = _discovery_url(season_code)
        calendar_html = fetch_calendar(url)

    by_round = parse_calendar(calendar_html)
    target = str(external_id)
    for round_number, refs in by_round.items():
        for ref in refs:
            if str(ref.external_id) == target:
                return round_number
    return None


def run() -> int:
    ap = argparse.ArgumentParser(prog="feb-discover")
    ap.add_argument("--season", required=True, help="season code (only 2025-2026)")
    ap.add_argument("--round", type=int, required=True, help="jornada number (1-based)")
    args = ap.parse_args()

    try:
        refs = discover_matches(args.season, args.round)
    except ConfigError as exc:
        print(f"CONFIG_ERROR: {exc}", file=sys.stderr)
        return 2
    except SourceError as exc:
        print(f"SOURCE_ERROR: {exc}", file=sys.stderr)
        return 3
    except Exception as exc:  # noqa: BLE001 — CLI boundary: unexpected -> 6
        print(f"UNEXPECTED_ERROR: {exc}", file=sys.stderr)
        return 6

    print(f"discovered={len(refs)}")
    for r in refs:
        print(
            f"{r.external_id} | round={r.round_number} | {r.scheduled_at} | "
            f"{r.home_team} - {r.away_team}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(run())