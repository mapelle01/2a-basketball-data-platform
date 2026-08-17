#!/usr/bin/env python3
"""FASE 22.1 — Match Discovery (Segunda FEB 2025-2026).

Descubre los partidos de una jornada de Segunda FEB desde la fuente pública
oficial de FEB (`baloncestoenvivo.feb.es/calendario.aspx`).

Fuentes:
    ESTE  (grupo por defecto): GET único
        https://baloncestoenvivo.feb.es/calendario.aspx?g=2&t=2025&nm=segundafeb
    OESTE (FASE 22.5): el grupo NO es alcanzable por URL GET (dropdown ASP.NET);
        se obtiene con un POST ASP.NET mínimo (stdlib, sin cookies/sesión):
        se parsean los hidden fields + el valor del dropdown del HTML y se
        reenvían con `_ctl0:MainContentPlaceHolderMaster:gruposDropDownList`
        apuntando al grupo OESTE. NO se usan Selenium/Playwright/requests.

El calendario publica la temporada completa del grupo seleccionado en una sola
página. Grupos soportados: ESTE y OESTE (7 partidos/jornada cada uno).

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
No imprime secretos: los hidden fields (incluido `_ctl0:token`, un JWT de la
página) se reenvían en el POST sin loguearse jamás.

Exit codes (CLI):
    2  configuración inválida (season/grupo no soportado, argumentos inválidos)
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
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Dict, List, Optional

DEFAULT_DISCOVERY_BASE = "https://baloncestoenvivo.feb.es/calendario.aspx"
COMP_ID = 2
COMP_CODE = "segundafeb"
SEASON_T = "2025"  # FEB usa el año de inicio: t=2025 -> temporada 2025-2026
SUPPORTED_SEASON = "2025-2026"  # FASE 25: override via env FEB_SEASON_CODE (e.g. 2026-2027)
SUPPORTED_GROUPS = ("ESTE", "OESTE")  # FASE 22.5: OESTE vía POST ASP.NET
GRUPO_SELECT_NAME = "_ctl0:MainContentPlaceHolderMaster:gruposDropDownList"
GRUPO_SELECT_TARGET = "_ctl0$MainContentPlaceHolderMaster$gruposDropDownList"
TZ_OFFSET = "+01:00"  # provisional, igual que FASE 21.B2
USER_AGENT = "feb-score-discover/1.0"
TIMEOUT_SECONDS = 30

_H1_JORNADA_RE = re.compile(
    r"<h1[^>]*>\s*Jornada\s+(\d+)\s+(\d{2}/\d{2}/\d{4})\s*</h1>", re.I
)
_TR_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S)
_PARTIDO_RE = re.compile(r"Partido\.aspx\?p=(\d+)")
_EQUIPO_RE = re.compile(r'class="equipo (local|visitante)".*?Equipo\.aspx\?i=\d+"[^>]*>([^<]+)</a>', re.S)

# --- ASP.NET postback (FASE 22.5): extracción del HTML del calendario
_HIDDEN_INPUT_RE = re.compile(
    r'<input[^>]*type="hidden"[^>]*name="([^"]+)"[^>]*value="([^"]*)"', re.I
)
_GRUPO_OPTION_RE = re.compile(r'<option[^>]*value="([^"]+)"[^>]*>([^<]*)</option>', re.S)
_GRUPO_SELECT_RE = re.compile(r'<select[^>]*name="' + re.escape(GRUPO_SELECT_NAME) + r'"[^>]*>(.*?)</select>', re.S)
_FORM_ACTION_RE = re.compile(r'<form[^>]*action="([^"]+)"', re.I)


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


def _configured_season() -> str:
    """Temporada activa: env ``FEB_SEASON_CODE`` o default ``2025-2026``.

    FASE 25 (auto-ingesta): cuando arranque 2026-2027 se settea
    ``FEB_SEASON_CODE=2026-2027`` y el resto del pipeline la usa sin cambios.
    """
    return _env("FEB_SEASON_CODE", SUPPORTED_SEASON) or SUPPORTED_SEASON


def _season_t(season_code: str) -> str:
    """Año de inicio de la temporada: `2026-2027` -> `2026` (param ``t`` de FEB)."""
    return season_code.split("-")[0]


def _discovery_url(season_code: str) -> str:
    """URL GET del calendario para la temporada soportada (sin postbacks)."""
    if season_code != _configured_season():
        raise ConfigError(
            f"unsupported season {season_code!r}; only {_configured_season()!r}"
        )
    base = _env("FEB_DISCOVERY_BASE_URL", DEFAULT_DISCOVERY_BASE) or DEFAULT_DISCOVERY_BASE
    return f"{base}?g={COMP_ID}&t={_season_t(season_code)}&nm={COMP_CODE}"


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


def _hidden_inputs(html_text: str) -> Dict[str, str]:
    """Hidden fields del formulario ASP.NET: `name` -> `value` (sin entidades)."""
    return {
        m.group(1): html.unescape(m.group(2))
        for m in _HIDDEN_INPUT_RE.finditer(html_text)
    }


def _grupo_value(html_text: str, group: str) -> Optional[str]:
    """Valor del `<option>` cuyo texto contiene `group` en el dropdown de grupos.

    Ej: `Liga Regular "ESTE"` -> "88879", `Liga Regular "OESTE"` -> "88880".
    Devuelve None si el grupo no aparece en el dropdown.
    """
    sel = _GRUPO_SELECT_RE.search(html_text)
    if not sel:
        return None
    for value, label in _GRUPO_OPTION_RE.findall(sel.group(1)):
        if group.upper() in html.unescape(label).upper():
            return value
    return None


def _post_grupo(base_url: str, page_html: str, group: str) -> str:
    """POST ASP.NET para cambiar el grupo del calendario (FASE 22.5).

    Reenvía los hidden fields de la página + el dropdown de grupos con el valor
    del grupo pedido. `base_url` es la URL final del GET (tras el redirect de
    `calendario.aspx`); el action del form es relativo a ella.

    No guarda cookies/sesiones persistentes (urllib sin CookieJar), no usa
    Selenium/Playwright y jamás imprime el hidden `_ctl0:token`.
    """
    action = _FORM_ACTION_RE.search(page_html)
    action = action.group(1) if action else ""
    post_url = urllib.parse.urljoin(base_url, action)
    data = _hidden_inputs(page_html)
    value = _grupo_value(page_html, group)
    if value is None:
        raise SourceError(f"group {group!r} not present in FEB grupos dropdown")
    data[GRUPO_SELECT_NAME] = value
    data["__EVENTTARGET"] = GRUPO_SELECT_TARGET
    data["__EVENTARGUMENT"] = ""
    body = urllib.parse.urlencode(data).encode("utf-8")
    req = urllib.request.Request(
        post_url,
        data=body,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html",
            "Content-Type": "application/x-www-form-urlencoded",
            "Referer": base_url,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:  # noqa: S310
            if not (200 <= resp.status < 300):
                raise SourceError(f"FEB POST {post_url} HTTP {resp.status}")
            return resp.read().decode("utf-8", "replace")
    except SourceError:
        raise
    except (urllib.error.URLError, urllib.error.HTTPError, OSError) as exc:
        raise SourceError(f"FEB {post_url} POST failed: {exc}") from exc


def fetch_calendar_group(season_code: str, group: str = "ESTE") -> str:
    """Calendario HTML del grupo pedido (ESTE: GET; OESTE: GET + POST ASP.NET).

    Para ESTE el comportamiento es idéntico al de FASE 22.1 (GET único). Para
    OESTE hace el GET base (obtiene hidden fields + dropdown) y un POST mínimo.
    Lanza ConfigError (grupo no soportado) o SourceError.
    """
    if season_code != _configured_season():
        raise ConfigError(
            f"unsupported season {season_code!r}; only {_configured_season()!r}"
        )
    if group not in SUPPORTED_GROUPS:
        raise ConfigError(
            f"unsupported group {group!r}; supported groups: {', '.join(SUPPORTED_GROUPS)}"
        )
    base_url = _discovery_url(season_code)
    page_html = fetch_calendar(base_url)
    if group == "ESTE":
        return page_html
    return _post_grupo(base_url, page_html, group)


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
    group: str = "ESTE",
) -> List[MatchRef]:
    """Descubre los partidos de una jornada de Segunda FEB 2025-2026.

    Args:
        season_code: solo `2025-2026` (config inválida -> SystemExit 2).
        round_number: número de jornada (>= 1; invalid -> SystemExit 2).
        calendar_html: HTML del calendario (offline/tests). Si es None se hace
            la obtención real a la fuente FEB para el `group` pedido.
        group: `ESTE` (default, GET único) u `OESTE` (POST ASP.NET, FASE 22.5).

    Returns:
        Lista de MatchRef de la jornada pedida (vacía si la jornada no existe),
        ordenada por `external_id`. Sin production, sin secrets.
    """
    if season_code != _configured_season():
        raise ConfigError(
            f"unsupported season {season_code!r}; only {_configured_season()!r}"
        )
    if group not in SUPPORTED_GROUPS:
        raise ConfigError(
            f"unsupported group {group!r}; supported groups: {', '.join(SUPPORTED_GROUPS)}"
        )
    if not isinstance(round_number, int) or isinstance(round_number, bool) or round_number < 1:
        raise ConfigError(
            f"invalid round {round_number!r}; expected integer >= 1"
        )

    if calendar_html is None:
        calendar_html = fetch_calendar_group(season_code, group)

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
    group: str = "ESTE",
) -> Optional[int]:
    """Jornada real de un match dado (para `--match-id` manual, FASE 22.4).

    Obtiene el calendario del grupo pedido (o acepta HTML offline) y busca el
    `external_id`; devuelve su round_number o None si el partido no está en el
    calendario. Coherente con el pipeline: la jornada SIEMPRE viene del discovery
    (nunca se inventa). Lanza ConfigError/SourceError igual que discover_matches().
    """
    if season_code != _configured_season():
        raise ConfigError(
            f"unsupported season {season_code!r}; only {_configured_season()!r}"
        )
    if group not in SUPPORTED_GROUPS:
        raise ConfigError(
            f"unsupported group {group!r}; supported groups: {', '.join(SUPPORTED_GROUPS)}"
        )
    if calendar_html is None:
        calendar_html = fetch_calendar_group(season_code, group)

    by_round = parse_calendar(calendar_html)
    target = str(external_id)
    for round_number, refs in by_round.items():
        for ref in refs:
            if str(ref.external_id) == target:
                return round_number
    return None


def run() -> int:
    ap = argparse.ArgumentParser(prog="feb-discover")
    ap.add_argument("--season", required=True, help="season code (default env FEB_SEASON_CODE or 2025-2026)")
    ap.add_argument("--round", type=int, required=True, help="jornada number (1-based)")
    ap.add_argument(
        "--group", default="ESTE", choices=list(SUPPORTED_GROUPS),
        help=f"grupo (default ESTE): {', '.join(SUPPORTED_GROUPS)}",
    )
    args = ap.parse_args()

    try:
        refs = discover_matches(args.season, args.round, group=args.group)
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