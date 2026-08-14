#!/usr/bin/env python3
"""Ingest a FEB results page into feb_score production.

Required environment:
  FEB_SCORE_API_KEY  Raw production API key (the 64-hex value only).
  FEB_SCORE_API_URL  Production API base URL.

The connector never logs the API key or FEB LiveStats token.
"""

from __future__ import annotations

import argparse
import os
import sys

from connectors.feb.client import DEFAULT_LIVE_ENDPOINTS, DEFAULT_RESULTS_URL, FEBClient
from connectors.feb.sink import ProductionSink, build_match_payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Ingest Segunda FEB data from the official FEB source")
    parser.add_argument("--results-url", default=DEFAULT_RESULTS_URL)
    parser.add_argument("--api-url", default=os.getenv("FEB_SCORE_API_URL", "https://feb-score-api-production.up.railway.app"))
    parser.add_argument("--limit", type=int, default=0, help="Maximum matches; 0 means all matches on the selected results page")
    parser.add_argument("--skip-live-stats", action="store_true", help="Do not call the per-match LiveStats API")
    args = parser.parse_args()

    api_key = os.getenv("FEB_SCORE_API_KEY", "").strip()
    if not api_key:
        print("ERROR: FEB_SCORE_API_KEY is required", file=sys.stderr)
        return 2

    client = FEBClient()
    sink = ProductionSink(args.api_url, api_key)

    results_html = client.fetch_results_page(args.results_url)
    matches = client.list_matches(results_html)
    if args.limit > 0:
        matches = matches[: args.limit]

    print(f"FEB source: {len(matches)} matches selected")
    accepted = 0
    failed = 0

    for index, match in enumerate(matches, start=1):
        try:
            match_html = client.fetch_match_page(match)
            endpoints = () if args.skip_live_stats else DEFAULT_LIVE_ENDPOINTS
            responses = client.fetch_live_stats(match, match_html, endpoints=endpoints)
            payload = build_match_payload(match, responses, source_url=match.match_url)
            result = sink.send_match(match, payload)
            accepted += 1
            print(f"[{index}/{len(matches)}] {match.external_id}: {match.home_team_name} - {match.away_team_name} -> {result.get('status', 'accepted')}")
        except Exception as exc:  # noqa: BLE001 - connector should continue across independent matches
            failed += 1
            print(f"[{index}/{len(matches)}] {match.external_id}: ERROR {exc}", file=sys.stderr)

    print(f"FEB ingest complete: accepted={accepted} failed={failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
