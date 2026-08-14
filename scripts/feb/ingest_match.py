#!/usr/bin/env python3
"""FASE 21.B2 — FEB Source Connector (real format).

Read-only fetch del BoxScore real de FEB (`intrafeb.feb.es/LiveStats.API/api/v1/BoxScore/{id}`)
-> normalize a `create_or_update_match` -> POST a la API (offline-first; production
POST solo con `FEB_API_KEY` real).

Reemplaza al primer prototipo del FASE 21.B1 que asumía un JSON genérico. Mantiene las
firmas de FASE 21.B1 (`to_command`, `_command_id`, `post_command`) para compatibilidad de tests.

Reglas B2:
  * NO secrets en Git (token vía env `FEB_TOKEN`; nunca loggeado ni en payload ni URLs).
  * `external_id` = match_id FEB (real).
  * `season_code` desde `FEB_SEASON_CODE` (explicit; no heurística).
  * `competition_id` lógico domémino (default `segunda-feb`); el `CompID` FEB real se
    preserva en `source`/headers -> no sustituye el logical id del domain.
  * `scheduled_at` parseado de `dd-mm-yyyy - HH:MM` a ISO-8601 con **offset provisional +01:00**
    (FEB no publica TZ en este campo -> decisión B2, generalización correcta en B3).
  * Player stats parseados desde `BOXSCORE.TEAM[].PLAYER[]` (NO se añaden al schema; el
    contrato `raw` es restrictivo `boxscore_ref`/`teamstats_ref` -> las stats completas se
    documentan como FASE 21.B3 persistent storage).
  * Idempotency: `command_id` UUIDv5 sobre `season_code|competition_id|external_id`.
  * `--fixture PATH --dry-run` funciona 100% offline (no exige `FEB_SOURCE_URL`/`FEB_TOKEN`).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

COMMAND_VERSION = "1.0"
ACTOR_ID = "ingestor-1"
ACTOR_ROLE = "system"

DEFAULT_COMPETITION_ID = "segunda-feb"
DEFAULT_BOXSCORE_BASE = "https://intrafeb.feb.es/LiveStats.API/api/v1/BoxScore"
TZ_OFFSET_B2 = "+01:00"  # FEB no publica TZ en starttime; Spain winter/summer provisional. B3 generalization.


def _env(name: str, default: Optional[str] = None) -> Optional[str]:
    v = os.environ.get(name, "").strip()
    if not v:
        return default
    return v


def _require_env(name: str) -> str:
    v = _env(name)
    if v is None:
        raise SystemExit(f"CONFIG_ERROR: missing required env var: {name}")
    return v


def _command_id(season_code: str, competition_id: str, external_id: str) -> str:
    """UUIDv5 deterministic over season_code|competition_id|external_id (idempotencia)."""
    name = f"{season_code}|{competition_id}|{external_id}"
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"feb-score-ingestor:{name}"))


def _now_iso() -> str:
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_starttime(raw: str) -> str:
    """`18-10-2025 - 19:00` -> `2025-10-18T19:00:00+01:00`.

    Decisión B2: FEB no incluye timezone en `starttime`; se asume hora local España
    (+01:00 de invierno). Generalización correcta (horario verano/real TZ) -> B3.
    """
    m = re.match(r"(\d{2})-(\d{2})-(\d{4})\s*-\s*(\d{2}):(\d{2})", raw.strip())
    if not m or len(m.group(0)) < 16:
        raise ValueError(f"unparseable starttime: {raw!r}")
    dd, mm, yyyy, HH, MM = m.groups()
    return f"{yyyy}-{mm}-{dd}T{HH}:{MM}:00{TZ_OFFSET_B2}"


def _team_ref(team: Dict[str, Any]) -> Dict[str, Any]:
    """HEADER.TEAM entry -> payload teamRef (id=team id; name preservado)."""
    if not isinstance(team, dict):
        raise ValueError("team entry is not a dict")
    return {
        "external_id": str(team.get("id", "")),
        "name": team.get("name", "") or "",
    }


def _player_stats(player: Dict[str, Any]) -> Dict[str, Any]:
    """BOXSCORE.TEAM[].PLAYER entry -> stats dict (real fields, no schema change).

    Field names mirror the real FEB payload keys (kebab/snake normalized to snake).
    """
    def num(v):  # FEB returns numerics as strings
        if v in (None, "",):
            return 0
        try:
            if "," in str(v) and "." not in str(v):
                # spanish decimal comma: "40,0" -> 0.40 (percentage handled by ref)
                return float(str(v).replace(",", ""))
            return float(v)
        except (TypeError, ValueError):
            return 0.0

    return {
        "id": str(player.get("id", "")),
        "no": str(player.get("no", "")),
        "name": player.get("name", "") or "",
        "min": num(player.get("min")),
        "pts": num(player.get("pts")),
        "reb": num(player.get("reb")),
        "assist": num(player.get("assist")),
        "val": num(player.get("val")),
        "to": num(player.get("to")),
        "bs": num(player.get("bs")),
        "st": num(player.get("st")),
        "pf": num(player.get("pf")),
        "p1m": num(player.get("p1m")),
        "p1a": num(player.get("p1a")),
        "p1p": num(player.get("p1p")),
        "p2m": num(player.get("p2m")),
        "p2a": num(player.get("p2a")),
        "p2p": num(player.get("p2p")),
        "p3m": num(player.get("p3m")),
        "p3a": num(player.get("p3a")),
        "p3p": num(player.get("p3p")),
        "fgm": num(player.get("fgm")),
        "fga": num(player.get("fga")),
        "fgp": num(player.get("fgp")),
    }


def parse_boxscore(boxscore: Dict[str, Any], match_id: str, season_code: str) -> Dict[str, Any]:
    """Transform the REAL FEB BoxScore JSON into the intermediate format used by to_command().

    Real fixture `HEADER`/`BOXSCORE` layout (verified):
      HEADER.CompID, HEADER.competition, HEADER.starttime ("dd-mm-yyyy - HH:MM"),
      HEADER.TEAM[0|1]{id,name,teamCode,clubCode,pts}, HEADER.QUARTERS.QUARTER[{n,scoreA,scoreB}],
      BOXSCORE.TEAM[{id,name,TOTAL,PLAYER[{...}]}]
    Team order in HEADER.TEAM defines home/away (FEB convention).
    """
    if not isinstance(boxscore, dict):
        raise ValueError("boxscore must be a JSON object")
    header = boxscore.get("HEADER")
    if not isinstance(header, dict):
        raise ValueError("boxscore missing HEADER object")

    teams = header.get("TEAM") or []
    if len(teams) != 2:
        raise ValueError(f"expected exactly 2 teams in HEADER.TEAM, got {len(teams)}")

    home_hdr = teams[0]
    away_hdr = teams[1]
    competition = header.get("competition", "") or ""
    comp_id = header.get("CompID", "")

    scheduled_at = parse_starttime(header.get("starttime", ""))

    quarters = (header.get("QUARTERS") or {}).get("QUARTER") or []
    partials: List[Dict[str, Any]] = []
    for q in quarters:
        if not isinstance(q, dict):
            continue
        partials.append({
            "period": int(q.get("n", 0)) if str(q.get("n", "")).isdigit() else 0,
            "home_score": int(q.get("scoreA", 0) or 0),
            "away_score": int(q.get("scoreB", 0) or 0),
        })
    # Final totals (HEADER.TEAM[].pts) — authoritative, not derived from quarters.
    home_score = int(home_hdr.get("pts", 0) or 0)
    away_score = int(away_hdr.get("pts", 0) or 0)

    # Player stats via BOXSCORE.TEAM[].PLAYER (aligned by team id with HEADER.TEAM order).
    box_teams = {str(t.get("id", "")): t for t in (boxscore.get("BOXSCORE", {}) or {}).get("TEAM", [])}
    home_players: List[Dict[str, Any]] = []
    away_players: List[Dict[str, Any]] = []
    _fill_players(box_teams, str(home_hdr.get("id", "")), home_players)
    _fill_players(box_teams, str(away_hdr.get("id", "")), away_players)

    return {
        "external_id": str(match_id),
        "competition": competition,
        "comp_id": str(comp_id),
        "season_code": season_code,
        "scheduling": {"scheduled_at": scheduled_at, "tz_policy": "B2: +01:00 assumed (FEB no TZ)", "next": "B3 real TZ"},
        "teams": {
            "home": {"id": str(home_hdr.get("id", "")), "name": home_hdr.get("name", "") or "",
                     "teamCode": str(home_hdr.get("teamCode", "")),
                     "clubCode": str(home_hdr.get("clubCode", "")),
                     "score": home_score},
            "away": {"id": str(away_hdr.get("id", "")), "name": away_hdr.get("name", "") or "",
                     "teamCode": str(away_hdr.get("teamCode", "")),
                     "clubCode": str(away_hdr.get("clubCode", "")),
                     "score": away_score},
        },
        "quarters": partials,
        "stats": {"home": home_players, "away": away_players},
    }


def _fill_players(box_teams: Dict[str, Dict[str, Any]], team_id: str, out: List[Dict[str, Any]]) -> None:
    t = box_teams.get(team_id)
    if not isinstance(t, dict):
        return
    for pl in (t.get("PLAYER") or []):
        out.append(_player_stats(pl))


def to_command(parsed: Dict[str, Any], competition_id: str) -> Dict[str, Any]:
    """Normalize parsed FEB match -> create_or_update_match command envelope.

    Contract-compliant: payload respects
    contracts/commands/create_or_update_match.v1.json (additionalProperties:false).
    Only the fields permitted by schema are emitted; player stats / full BoxScore are
    NOT embedded (reserved for FASE 21.B3 persistence). Preserved refs go in source/raw.
    """
    ext = parsed["external_id"]
    season_code = parsed["season_code"]
    teams = parsed["teams"]
    home, away = teams["home"], teams["away"]

    command_id = _command_id(season_code, competition_id, ext)
    now = _now_iso()

    # Round number from HEADER.round (real FEB provides "round"; fallback via quarters count heuristic is avoided).
    # parsed does not carry round; derive 0 when absent (schema round_number is optional, min 1).
    round_number = 1

    return {
        "command_id": command_id,
        "meta": {"version": COMMAND_VERSION, "issued_at": now},
        "actor": {"id": ACTOR_ID, "role": ACTOR_ROLE},
        "payload": {
            "external_id": ext,
            "competition_id": competition_id,
            "season_code": season_code,
            "round_number": round_number,
            "scheduled_at": parsed["scheduling"]["scheduled_at"],
            "home_team": {
                "external_id": home["id"],
                "name": home["name"],
            },
            "away_team": {
                "external_id": away["id"],
                "name": away["name"],
            },
            "venue": {
                "name": home.get("teamCode") or "",
                "city": "",
            },
            "source": {
                "id": "feb-intrafeb",
                "fetched_at": now,
                "s3_path": f"s3://feb-live/{season_code}/{ext}_boxscore.json",
            },
            "raw": {
                "boxscore_ref": f"s3://feb-live/{season_code}/{ext}_boxscore.json",
                "teamstats_ref": f"s3://feb-live/{season_code}/{ext}_teamstats.json",
            },
        },
        # Extended metadata kept OUT of payload (would break schema); attached for dry-run/trace.
        "_stats": {
            "comp_id": parsed["comp_id"],
            "competition": parsed["competition"],
            "home_score": home["score"],
            "away_score": away["score"],
            "quarters": parsed["quarters"],
            "home_players": home["score"],  # placeholder; real counts kept in parsed.stats
            "player_counts": {"home": len(parsed["stats"]["home"]), "away": len(parsed["stats"]["away"])},
            "scheduled_raw_tz": parsed["scheduling"]["tz_policy"],
        },
    }


def post_command(base_url: str, api_key: str, command: Dict[str, Any]) -> Dict[str, Any]:
    """POST create_or_update_match. Key never logged (masked by caller / run logs)."""
    payload = {k: v for k, v in command.items() if not k.startswith("_")}  # strip dry-run/trace keys
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{base_url.rstrip('/')}/v1/commands/create_or_update_match",
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
            "X-Request-Id": command["command_id"],
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return {"status": resp.status, "body": json.loads(resp.read().decode("utf-8"))}
    except urllib.error.HTTPError as e:
        return {"status": e.code, "body": e.read().decode("utf-8", "replace")}


def fetch_feb_boxscore(match_id: str, token: str, base_url: str = DEFAULT_BOXSCORE_BASE) -> Dict[str, Any]:
    """GET real FEB BoxScore. Token NEVER printed/stored/URLized."""
    url = f"{base_url.rstrip('/')}/{match_id}"
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {token}",  # never exposed in logs/errors by caller
            "User-Agent": "feb-score-connector/1.0",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 (configurable, FEB real endpoint)
        if not (200 <= resp.status < 300):
            raise RuntimeError(f"FEB {url} HTTP {resp.status}")
        return json.loads(resp.read().decode("utf-8"))


def _run_dry(parsed: Dict[str, Any], competition_id: str, season_code: str) -> Dict[str, Any]:
    cmd = to_command(parsed, competition_id)
    t = cmd["payload"]
    print(f"external_id={t['external_id']}")
    print(f"competition={parsed['competition']} (CompID={parsed['comp_id']})")
    print(f"season={season_code}")
    print(f"home_team={t['home_team']['external_id']} ({t['home_team']['name']})")
    print(f"away_team={t['away_team']['external_id']} ({t['away_team']['name']})")
    print(f"scheduled_at={t['scheduled_at']} ({cmd['_stats']['scheduled_raw_tz']})")
    print(f"home_score={cmd['_stats']['home_score']}")
    print(f"away_score={cmd['_stats']['away_score']}")
    print(f"quarters={[(q['period'],q['home_score'],q['away_score']) for q in cmd['_stats']['quarters']]}")
    print(f"players= home:{cmd['_stats']['player_counts']['home']} away:{cmd['_stats']['player_counts']['away']}")
    print(f"command_id={cmd['command_id']}")
    print("DRY_RUN")
    return cmd


def run() -> int:
    ap = argparse.ArgumentParser(prog="feb-ingest")
    ap.add_argument("--fixture", help="local BoxScore JSON path (offline; skips FEB_SOURCE_URL/FEB_TOKEN)")
    ap.add_argument("--dry-run", action="store_true", help="build+print command only; NO POST")
    ap.add_argument("--match-id", help="FEB match id to fetch via API (requires FEB_TOKEN)")
    args = ap.parse_args()

    season_code = _require_env("FEB_SEASON_CODE")
    competition_id = _env("FEB_COMPETITION_ID", DEFAULT_COMPETITION_ID)

    # Fixture/offline path: NO requirement for source url or token.
    if args.fixture:
        with open(args.fixture, "rb") as f:
            box = json.loads(f.read().decode("utf-8"))
        parsed = parse_boxscore(box, match_id=os.environ.get("FEB_MATCH_ID", _external_id_from_path(args.fixture)),
                                season_code=season_code)
        cmd = _run_dry(parsed, competition_id, season_code)
        if not args.dry_run:
            target = _require_env("FEB_TARGET_API")
            api_key = _require_env("FEB_API_KEY")
            res = post_command(target, api_key, cmd)
            print(f"POST external_id={parsed['external_id']} command_id={cmd['command_id']} HTTP {res['status']}")
            return 0 if res["status"] in (200, 409) else 4
        return 0

    # Real FEB fetch path (needs token + match-id).
    token = _require_env("FEB_TOKEN")
    match_id = args.match_id or _require_env("FEB_MATCH_ID")
    base = _env("FEB_BOX_SCORE_BASE_URL", DEFAULT_BOXSCORE_BASE)
    box = fetch_feb_boxscore(match_id, token, base)
    parsed = parse_boxscore(box, match_id=match_id, season_code=season_code)

    if args.dry_run:
        _run_dry(parsed, competition_id, season_code)
        return 0

    target = _require_env("FEB_TARGET_API")
    api_key = _require_env("FEB_API_KEY")
    cmd = to_command(parsed, competition_id)
    res = post_command(target, api_key, cmd)
    print(f"OK external_id={parsed['external_id']} command_id={cmd['command_id']} HTTP {res['status']}")
    return 0 if res["status"] in (200, 409) else 4


def _external_id_from_path(path: str) -> str:
    m = re.search(r"boxscore_(\d+)\.json$", path)
    if not m:
        raise SystemExit(f"CONFIG_ERROR: could not derive match_id from fixture path {path!r}; set FEB_MATCH_ID")
    return m.group(1)


if __name__ == "__main__":
    sys.exit(run())
