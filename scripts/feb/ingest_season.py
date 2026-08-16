#!/usr/bin/env python3
"""FASE 22.3 — Season Backfill (Segunda FEB 2025-2026, grupo ESTE).

Orquestador de temporada que reutiliza las piezas existentes SIN crear una
segunda arquitectura:

    discover_matches.py (FASE 22.1)
        -> List[MatchRef] por jornada
    ingest_round.py (FASE 22.2)
        -> ingesta individual (reutiliza ingest_match.py)
    ingest_season.py (ESTA FASE, solo orquestador)
        -> bucle de jornadas + resumen agregado

El runner NO duplica lógica de ingestión: por jornada delega en
`ingest_round.run_round` (que a su vez reutiliza `ingest_match.*`). El único
uso directo de `discover_matches` es la enumeración determinista de las
jornadas disponibles: un único GET al calendario + `parse_calendar` para
detectar el rango real de jornadas (no se asume ciegamente "26").

Aislamiento de errores:
  * un partido fallido -> registrado por run_round, la jornada continúa;
  * una jornada fallida -> se registra y la siguiente jornada continúa
    cuando es seguro; nunca se aborta la temporada por un fallo local.

Exit codes (coherentes con discover_matches/ingest_round):
    0  todas las jornadas procesadas correctamente (failed global = 0)
    1  hubo al menos un fallo de ingestión (match o jornada)
    2  error de configuración/argumentos
    3  discovery de temporada fallido (calendario no disponible/parseable)
    6  error inesperado

Seguridad: nunca imprime FEB_TOKEN, FEB_API_KEY ni Authorization headers.
Los errores se sanitizan sustituyendo el valor de token/api_key si aparecieran.

Grupo: por defecto ESTE. Desde FASE 22.5 también OESTE (POST ASP.NET mínimo en
discover_matches); `discover_rounds` delega en `DM.fetch_calendar_group`.
"""
from __future__ import annotations

import argparse
import contextlib
import io
import os
import re
import sys
import time
from typing import Any, Dict, List, Optional

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import discover_matches as DM  # noqa: E402  (FASE 22.1)
import ingest_round as IR      # noqa: E402  (FASE 22.2)

SUPPORTED_GROUP = "ESTE"
SUPPORTED_GROUPS = DM.SUPPORTED_GROUPS  # FASE 22.5: ("ESTE", "OESTE")
_DEFAULT_MAX_ROUND = 40  # cota de seguridad para enumerar; el rango real lo da la fuente

_ROUND_SUMMARY_RE = re.compile(r"^(discovered|match_ok|stats_ok|failed)=(\d+)$")


class ConfigError(RuntimeError):
    """Configuración inválida (grupo no soportado, rango inválido) -> exit 2."""


def _sanitize(msg: str) -> str:
    """Redacta FEB_TOKEN / FEB_API_KEY si aparecieran en un mensaje."""
    for name in ("FEB_TOKEN", "FEB_API_KEY"):
        val = os.environ.get(name, "")
        if val:
            msg = msg.replace(val, "[redacted]")
    return (msg or "")[:300]


def discover_rounds(season_code: str, group: str = SUPPORTED_GROUP) -> Dict[int, List[DM.MatchRef]]:
    """Enumeración determinista de las jornadas de la temporada.

    Un único fetch del calendario (GET para ESTE, POST ASP.NET para OESTE en
    `discover_matches.fetch_calendar_group`) + `parse_calendar` ->
    {round: [MatchRef]}. Reutiliza `discover_matches.*`; no asume un número fijo
    de jornadas. Lanza DM.ConfigError (grupo/season inválidos) o DM.SourceError
    (fuente no disponible / sin jornadas parseables).
    """
    if group not in SUPPORTED_GROUPS:
        raise ConfigError(
            f"unsupported group {group!r}; supported groups: {', '.join(SUPPORTED_GROUPS)}"
        )
    html = DM.fetch_calendar_group(season_code, group)
    by_round = DM.parse_calendar(html)
    if not by_round:
        raise DM.SourceError("no jornadas parsed from calendar HTML")
    return by_round


def _selected_rounds(
    by_round: Dict[int, List[DM.MatchRef]],
    round_from: Optional[int],
    round_to: Optional[int],
) -> List[int]:
    """Jornadas descubiertas dentro del rango [round_from, round_to] (inclusive)."""
    rounds = sorted(r for r in by_round)
    if round_from is not None:
        rounds = [r for r in rounds if r >= round_from]
    if round_to is not None:
        rounds = [r for r in rounds if r <= round_to]
    return rounds


def _capture_run_round(season_code: str, round_number: int, group: str) -> tuple[int, str]:
    """Ejecuta run_round capturando su stdout; devuelve (exit_code, output)."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = IR.run_round(season_code, round_number, group=group)
    return rc, buf.getvalue()


def _parse_round_summary(output: str) -> Dict[str, int]:
    """Parsea las líneas `discovered=.. match_ok=.. stats_ok=.. failed=..` de run_round."""
    counts = {"discovered": 0, "match_ok": 0, "stats_ok": 0, "failed": 0}
    for line in output.splitlines():
        m = _ROUND_SUMMARY_RE.match(line.strip())
        if m:
            counts[m.group(1)] = int(m.group(2))
    return counts


def _failed_lines(output: str) -> List[str]:
    return [ln for ln in output.splitlines() if "FAILED" in ln][:20]


def run_season(
    season_code: str,
    group: str = SUPPORTED_GROUP,
    round_from: Optional[int] = None,
    round_to: Optional[int] = None,
    dry_run: bool = False,
    delay: float = 0.0,
) -> int:
    """Backfill de la temporada: descubre jornadas, procesa cada una y agrega.

    `delay` = segundos de espera entre jornadas (rate-limit real de FEB BoxScore:
    fetchs seguidos devuelven HTTP 429). Devuelve el exit code global
    (0 ok, 1 hubo fallos). En dry-run solo descubre y reporta volumen;
    NO hace POST ni toca Production.
    """
    if round_from is not None and round_to is not None and round_from > round_to:
        raise ConfigError(
            f"invalid range: round_from={round_from} > round_to={round_to}"
        )

    by_round = discover_rounds(season_code, group)
    rounds = _selected_rounds(by_round, round_from, round_to)

    if dry_run:
        _print_dry_run(season_code, group, by_round, rounds)
        return 0

    total_discovered = sum(len(by_round[r]) for r in rounds)
    print("=" * 40)
    print("FASE 22.3 — SEASON BACKFILL")
    print("=" * 40)
    print()
    print(f"season={season_code}")
    print(f"group={group}")
    print()
    print(f"rounds_discovered={len(rounds)}")
    print(f"matches_discovered={total_discovered}")
    print()

    per_round: List[Dict[str, Any]] = []
    for idx, r in enumerate(rounds):
        if idx > 0 and delay > 0:
            time.sleep(delay)
        try:
            rc, output = _capture_run_round(season_code, r, group)
            counts = _parse_round_summary(output)
            failed_lines = _failed_lines(output)
        except Exception as exc:  # noqa: BLE001 — aislamiento por jornada
            counts = {"discovered": len(by_round[r]), "match_ok": 0, "stats_ok": 0,
                      "failed": len(by_round[r])}
            failed_lines = [f"ROUND {r} EXCEPTION: {_sanitize(str(exc))}"]
            rc = 1
        per_round.append({"round": r, **counts, "rc": rc, "failed_lines": failed_lines})

    ok = sum(1 for pr in per_round if pr["failed"] == 0)
    matches_ok = sum(pr["match_ok"] for pr in per_round)
    stats_ok = sum(pr["stats_ok"] for pr in per_round)
    failed = sum(pr["failed"] for pr in per_round)

    print("=" * 40)
    print("ROUND SUMMARY")
    print("=" * 40)
    print()
    for pr in per_round:
        print(f"round={pr['round']}  discovered={pr['discovered']}  "
              f"match_ok={pr['match_ok']}  stats_ok={pr['stats_ok']}  failed={pr['failed']}")
        for ln in pr["failed_lines"]:
            print(f"    {ln}")
    print()
    print("=" * 40)
    print("SEASON TOTALS")
    print("=" * 40)
    print()
    print(f"rounds_discovered={len(rounds)}")
    print(f"rounds_processed={len(per_round)}")
    print(f"matches_discovered={total_discovered}")
    print(f"matches_ok={matches_ok}")
    print(f"stats_ok={stats_ok}")
    print(f"failed={failed}")
    print()
    print("=" * 40)
    print(f"STATUS: {'PASS' if failed == 0 else 'PARTIAL'}")
    print("=" * 40)
    return 0 if failed == 0 else 1


def _print_dry_run(
    season_code: str,
    group: str,
    by_round: Dict[int, List[DM.MatchRef]],
    rounds: List[int],
) -> None:
    total = sum(len(by_round[r]) for r in rounds)
    print("FASE 22.3 — SEASON BACKFILL (DRY RUN)")
    print()
    print(f"season={season_code}")
    print(f"group={group}")
    print()
    print(f"rounds={len(rounds)}")
    print(f"matches={total}")
    print()
    print("rounds:", ", ".join(str(r) for r in rounds) or "(none)")
    print()
    print("DRY_RUN")
    print("POST disabled")


def run() -> int:
    ap = argparse.ArgumentParser(prog="feb-ingest-season")
    ap.add_argument("--season", required=True, help="season code (only 2025-2026)")
    ap.add_argument("--group", default=SUPPORTED_GROUP, help=f"group (default {SUPPORTED_GROUP}): {', '.join(SUPPORTED_GROUPS)}")
    ap.add_argument("--round-from", type=int, default=None, help="first round to process (1-based, inclusive)")
    ap.add_argument("--round-to", type=int, default=None, help="last round to process (1-based, inclusive)")
    ap.add_argument("--dry-run", action="store_true", help="discover + report volume; NO POST")
    ap.add_argument("--delay", type=float, default=0.0,
                    help="seconds to wait between rounds (FEB rate-limit 429)")
    args = ap.parse_args()

    if args.round_from is not None and args.round_from < 1:
        print(f"CONFIG_ERROR: round_from must be >= 1, got {args.round_from}", file=sys.stderr)
        return 2
    if args.round_to is not None and args.round_to < 1:
        print(f"CONFIG_ERROR: round_to must be >= 1, got {args.round_to}", file=sys.stderr)
        return 2

    try:
        return run_season(
            args.season,
            group=args.group,
            round_from=args.round_from,
            round_to=args.round_to,
            dry_run=args.dry_run,
            delay=args.delay,
        )
    except ConfigError as exc:
        print(f"CONFIG_ERROR: {exc}", file=sys.stderr)
        return 2
    except DM.ConfigError as exc:
        print(f"CONFIG_ERROR: {exc}", file=sys.stderr)
        return 2
    except DM.SourceError as exc:
        print(f"SOURCE_ERROR: {exc}", file=sys.stderr)
        return 3
    except Exception as exc:  # noqa: BLE001 — CLI boundary: unexpected -> 6
        print(f"UNEXPECTED_ERROR: {_sanitize(str(exc))}", file=sys.stderr)
        return 6


if __name__ == "__main__":
    sys.exit(run())