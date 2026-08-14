#!/usr/bin/env python3
"""FASE 21.B1 — FEB Source Connector (read-only fetch -> create_or_update_match command).

Minimal-change connector: it is the *source side* of the existing command-driven
architecture. It does NOT modify the domain, the API image, staging or production
variables. It only translates a FEB source row (fetched read-only from
``FEB_SOURCE_URL``) into the existing ``create_or_update_match`` command payload
(defined in ``contracts/commands/create_or_update_match.v1.json``) and submits it
to the API via HTTP (POST /v1/commands/create_or_update_match).

Design goals:
  * Idempotent: ``command_id`` is a UUIDv5 deterministic over
    ``season_code|competition_id|external_id`` -> re-running the same source row
    yields the same command_id, so the server-side idempotency (command_id
    dedup in outbox + domain) makes the ingestion idempotent by construction.
  * No secrets in Git: the API key is read from ``FEB_API_KEY`` env var only.
  * No tokens printed: only HTTP status / command_id / external_id are logged.
  * Deterministic external_id from the source.
  * Explicit error handling for FEB fetch / API 4xx / 5xx.
  * No assumptions about staging/prod: target & key come from env vars.

Env:
  FEB_SOURCE_URL      URL that returns one JSON match (read-only source).
  FEB_TARGET_API      Base API URL, e.g. https://feb-score-api-production.up.railway.app
  FEB_API_KEY         Production API key (64-hex raw). NOT printed.
  FEB_COMPETITION_ID  Logical competition id in the domain (default: segunda-feb).

Exit codes: 0 success, 2 bad env/config, 3 source fetch error, 4 command rejected
by API, 5 idempotency-conflict expected (rare), 6 unexpected.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

CONTRACT_VERSION = "1.0"
ACTOR_ID = "ingestor-1"          # system actor (schema: id min 1, role system)
COMMAND_VERSION = "1.0"


def _env(name: str, default: Optional[str] = None) -> str:
    v = os.environ.get(name, "").strip()
    if not v and default is None:
        raise SystemExit(f"missing required env var: {name}")
    return v or default


def _command_id(season_code: str, competition_id: str, external_id: str) -> str:
    """Deterministic UUIDv5 idempotency key -> re-ingest = same command = idempotent."""
    name = f"{season_code}|{competition_id}|{external_id}"
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"feb-score-ingestor:{name}"))


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def fetch_source(url: str) -> Dict[str, Any]:
    """Read-only fetch of a single match from the FEB source. No mutations."""
    req = urllib.request.Request(url, headers={"User-Agent": "feb-score-connector/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 (configurable source URL)
        if not (200 <= resp.status < 300):
            raise RuntimeError(f"FEB source {url} returned HTTP {resp.status}")
        return json.loads(resp.read().decode("utf-8"))


def to_command(source: Dict[str, Any], competition_id: str) -> Dict[str, Any]:
    """Normalize a FEB source row to the create_or_update_match command envelope.

    Mirrors contracts/commands/create_or_update_match.v1.json exactly. The
    payload carries the original external_id from FEB; the command_id stays
    deterministic so replays are idempotent.
    """
    p = source["payload"]
    season_code = p["season_code"]
    ext = p["external_id"]
    cid = _command_id(season_code, competition_id, ext)

    source_ref = {
        "id": source.get("source", "feb-api"),
        "fetched_at": source.get("fetched_at") or _now_iso(),
        "s3_path": (p.get("raw", {}) or {}).get("boxscore_ref") or f"s3://raw/{ext}_boxscore.json",
    }

    cmd: Dict[str, Any] = {
        "command_id": cid,
        "meta": {"version": COMMAND_VERSION, "issued_at": _now_iso()},
        "actor": {"id": ACTOR_ID, "role": "system"},
        "payload": {
            "external_id": ext,
            "season_code": season_code,
            "round_number": p.get("round_number", 1),
            "scheduled_at": p["scheduled_at"],
            "home_team": p["home_team"],
            "away_team": p["away_team"],
            "venue": p.get("venue") or {},
            "source": source_ref,
            "raw": p.get("raw", {"boxscore_ref": source_ref["s3_path"]}),
        },
    }
    return cmd


def post_command(base_url: str, api_key: str, command: Dict[str, Any]) -> Dict[str, Any]:
    """Submit the command to the production API. Key is never logged."""
    body = json.dumps(command).encode("utf-8")
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


def run() -> int:
    try:
        source_url = _env("FEB_SOURCE_URL")
        target_api = _env("FEB_TARGET_API")
        api_key = _env("FEB_API_KEY")
        competition_id = os.environ.get("FEB_COMPETITION_ID", "segunda-feb")

        source = fetch_source(source_url)
        command = to_command(source, competition_id)

        # Traceability WITHOUT secrets: only command_id + external_id + HTTP status.
        ext = command["payload"]["external_id"]
        print(f"ingest external_id={ext} command_id={command['command_id']} "
              f"competition={competition_id} season={command['payload']['season_code']}")

        result = post_command(target_api, api_key, command)
        status = result["status"]
        if status == 200:
            print(f"OK external_id={ext} command_id={command['command_id']} HTTP {status}")
            return 0
        if status == 409:
            print(f"IDEMPOTENT external_id={ext} command_id={command['command_id']} HTTP 409 (already accepted)")
            return 0
        print(f"REJECTED external_id={ext} HTTP {status} body={result['body'][:200]}")
        return 4
    except SystemExit as e:
        print(f"CONFIG_ERROR: {e}")
        return 2
    except urllib.error.HTTPError as e:
        print(f"SOURCE_ERROR HTTP {e.code} {e.reason}")
        return 3
    except Exception as e:  # noqa: BLE001
        print(f"UNEXPECTED_ERROR: {type(e).__name__}")
        return 6


if __name__ == "__main__":
    sys.exit(run())
