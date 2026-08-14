#!/usr/bin/env python3
"""Manual smoke (NEVER part of CI): validates a REAL FEB BoxScore fetch.

Usage:
    FEB_TOKEN='...' python3 scripts/feb/smoke_fetch_feb.py --match-id 2486864
    FEB_TOKEN='...' python3 scripts/feb/smoke_fetch_feb.py --match-id 2486864 --out /tmp/match.json

This does:
  - read FEB_TOKEN from env (never printed)
  - GET https://intrafeb.feb.es/LiveStats.API/api/v1/BoxScore/<match_id>
  - expect HTTP 200 + JSON with HEADER and BOXSCORE keys
  - optionally write raw JSON to --out (for audit; no secrets are inside the body)

Not collected or run by pytest/CI. Use only against matches you are authorized to fetch.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

DEFAULT_BASE = "https://intrafeb.feb.es/LiveStats.API/api/v1/BoxScore"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--match-id", required=True)
    ap.add_argument("--out", required=False, help="write raw JSON here (audit)")
    ap.add_argument("--base-url", default=DEFAULT_BASE)
    args = ap.parse_args()

    token = os.environ.get("FEB_TOKEN", "").strip()
    if not token:
        print("CONFIG_ERROR: FEB_TOKEN env var required", file=sys.stderr)
        return 2
    if "=" in token or token.lower().startswith("bearer ") or "\n" in token:
        print("CONFIG_ERROR: FEB_TOKEN appears malformed (contains '=' or Bearer prefix)", file=sys.stderr)
        return 2

    url = f"{args.base_url.rstrip('/')}/{args.match_id}"
    req = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "Authorization": f"Bearer {token}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 (FEB real endpoint)
            status = resp.status
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        print(f"FEB HTTP {e.code} for {args.match_id}")  # URL-safe to print (no token)
        return 3

    if status != 200:
        print(f"ERROR status={status}")
        return 4
    if not isinstance(data, dict) or "HEADER" not in data or "BOXSCORE" not in data:
        print("ERROR response missing HEADER/BOXSCORE")
        return 5

    # Only non-sensitive facts are echoed.
    print(f"OK match_id={args.match_id} comp_id={data['HEADER'].get('CompID')} "
          f"competition={data['HEADER'].get('competition')} teams={len(data['HEADER'].get('TEAM', []))}")

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(data, f)
        print(f"raw json written to {args.out} (no secrets; body is FEB public content)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
