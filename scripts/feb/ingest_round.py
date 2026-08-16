#!/usr/bin/env python3
"""FASE 22.2 — Bulk Ingestion Runner (jornada de Segunda FEB).

Orquestador que conecta:

    discover_matches()            (scripts/feb/discover_matches.py, FASE 22.1)
        -> List[MatchRef]
        -> ingesta individual de cada partido
        -> create_or_update_match + upsert_match_stats   (scripts/feb/ingest_match.py, FASE 21.B2/B3)
        -> resultado agregado de la jornada

NO duplica lógica de ingestión: reutiliza 100% `ingest_match.py`
(`fetch_feb_boxscore`, `parse_boxscore`, `to_command`, `to_stats_command`,
`post_command`, `post_stats_command`) y `discover_matches.py`
(`discover_matches`, `MatchRef`, `ConfigError`, `SourceError`).

Aislamiento de errores: un fallo en un partido NO aborta la jornada; se registra
el error sanitizado y se continúa. Al final se imprime el resumen agregado.

Exit codes (coherentes con discover_matches.py):
    0  todos los partidos procesados correctamente
    1  hubo al menos un fallo de ingestión
    2  error de configuración/argumentos
    3  discovery fallido
    6  error inesperado

Seguridad: nunca imprime FEB_TOKEN, FEB_API_KEY ni Authorization headers.
Los errores se sanitizan sustituyendo el valor de token/api_key si aparecieran.

Grupo: por defecto ESTE (GET). Desde FASE 22.5 también OESTE (POST ASP.NET
mínimo en discover_matches); ambos grupos se resuelven en discovery.
"""
from __future__ import annotations

import argparse
import os
import sys
from typing import Any, Dict, List, Optional

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import discover_matches as DM  # noqa: E402  (FASE 22.1)
import ingest_match as IM      # noqa: E402  (FASE 21.B2/B3)

_OK_STATUSES = (200, 201, 204, 409)  # mismas que ingest_match._post_and_report
SUPPORTED_GROUPS = DM.SUPPORTED_GROUPS  # FASE 22.5: ("ESTE", "OESTE")


class ConfigError(RuntimeError):
    """Configuración inválida (grupo no soportado) -> exit 2."""


def _sanitize_error(exc: Exception, token: Optional[str], api_key: Optional[str]) -> str:
    """Error sanitizado: sustituye cualquier aparición de token/api_key."""
    msg = str(exc) or type(exc).__name__
    for secret in (token, api_key):
        if secret:
            msg = msg.replace(secret, "[redacted]")
    return msg[:300]


def process_one(
    ref: DM.MatchRef,
    *,
    season_code: str,
    competition_id: str,
    token: str,
    target: str,
    api_key: str,
    base_url: str,
) -> Dict[str, Any]:
    """Procesa un MatchRef: fetch -> parse -> create_or_update_match -> upsert_match_stats.

    Aislado: cualquier excepción se captura y se reporta como error sanitizado
    sin abortar la jornada. Devuelve:
        external_id, match_ok, stats_ok, ok, error
    """
    ext = ref.external_id
    try:
        box = IM.fetch_feb_boxscore(str(ext), token, base_url)
        parsed = IM.parse_boxscore(
            box, match_id=str(ext), season_code=season_code,
            round_number=ref.round_number,  # FASE 22.4: jornada real del discovery
        )
        cmd = IM.to_command(parsed, competition_id)
        res = IM.post_command(target, api_key, cmd)
        if res["status"] not in _OK_STATUSES:
            return {
                "external_id": ext, "match_ok": False, "stats_ok": False, "ok": False,
                "error": f"match HTTP {res['status']}",
            }
        stats_cmd = IM.to_stats_command(parsed, competition_id)
        sres = IM.post_stats_command(target, api_key, stats_cmd)
        stats_ok = sres["status"] in _OK_STATUSES
        return {
            "external_id": ext, "match_ok": True, "stats_ok": stats_ok, "ok": stats_ok,
            "error": None if stats_ok else f"stats HTTP {sres['status']}",
        }
    except Exception as exc:  # noqa: BLE001 — aislamiento por partido
        return {
            "external_id": ext, "match_ok": False, "stats_ok": False, "ok": False,
            "error": _sanitize_error(exc, token, api_key),
        }


def _run_dry(refs: List[DM.MatchRef], season_code: str, round_number: int, group: str) -> int:
    print("FASE 22.2 DRY RUN")
    print()
    print(f"season={season_code}")
    print(f"round={round_number}")
    print(f"group={group}")
    print()
    print(f"discovered={len(refs)}")
    print()
    for r in refs:
        print(f"{r.external_id} {r.home_team} - {r.away_team} | {r.scheduled_at}")
    print()
    print("POST disabled")
    return 0


def run_round(
    season_code: str,
    round_number: int,
    group: str = "ESTE",
    dry_run: bool = False,
) -> int:
    """Descubre la jornada y procesa todos sus partidos (o solo muestra en dry-run)."""
    if group not in SUPPORTED_GROUPS:
        raise ConfigError(
            f"unsupported group {group!r}; supported groups: {', '.join(SUPPORTED_GROUPS)}"
        )

    refs = DM.discover_matches(season_code, round_number, group=group)

    if dry_run:
        return _run_dry(refs, season_code, round_number, group)

    token = IM._require_env("FEB_TOKEN")
    target = IM._require_env("FEB_TARGET_API")
    api_key = IM._require_env("FEB_API_KEY")
    competition_id = IM._env("FEB_COMPETITION_ID", IM.DEFAULT_COMPETITION_ID)
    base_url = IM._env("FEB_BOX_SCORE_BASE_URL", IM.DEFAULT_BOXSCORE_BASE)

    results: List[Dict[str, Any]] = []
    for ref in refs:
        res = process_one(
            ref,
            season_code=season_code,
            competition_id=competition_id,
            token=token,
            target=target,
            api_key=api_key,
            base_url=base_url,
        )
        results.append(res)
        status = "OK" if res["ok"] else "FAILED"
        suffix = f" {res['error']}" if not res["ok"] else ""
        print(f"{res['external_id']} {status}{suffix}")

    ok = sum(1 for r in results if r["ok"])
    match_ok = sum(1 for r in results if r["match_ok"])
    stats_ok = sum(1 for r in results if r["stats_ok"])
    print(f"discovered={len(refs)}")
    print(f"match_ok={match_ok}")
    print(f"stats_ok={stats_ok}")
    print(f"failed={len(results) - ok}")
    return 0 if ok == len(results) else 1


def run() -> int:
    ap = argparse.ArgumentParser(prog="feb-ingest-round")
    ap.add_argument("--season", required=True, help="season code (only 2025-2026)")
    ap.add_argument("--round", type=int, required=True, help="jornada number (1-based)")
    ap.add_argument("--group", default="ESTE", help=f"group (default ESTE): {', '.join(SUPPORTED_GROUPS)}")
    ap.add_argument("--dry-run", action="store_true", help="discover + list; NO POST")
    args = ap.parse_args()

    try:
        return run_round(args.season, args.round, args.group, args.dry_run)
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
        print(f"UNEXPECTED_ERROR: {exc}", file=sys.stderr)
        return 6


if __name__ == "__main__":
    sys.exit(run())