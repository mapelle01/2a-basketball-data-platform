"""Run the Content Engine against the CONFIGURED database (sqlite or postgres).

Unlike generate_examples.py (fixture data), this hits the real backend picked
by configuration:
  - FEB_SCORE_DATABASE_URL set  → PostgreSQL (e.g. production/staging)
  - otherwise                   → SQLite (FEB_SCORE_DB, default feb_score.db)

Every fact traces to the data platform; a round with no finalized matches
produces no content (never invented).

Usage:
    .venv/bin/python scripts/content/run_live_pipeline.py <season_code> <round_number> [top_n]

Example:
    .venv/bin/python scripts/content/run_live_pipeline.py 2025-2026 12
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from feb_score.infrastructure.wiring import build_gateway  # noqa: E402


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2

    season_code = argv[0]
    round_number = int(argv[1])
    top_n = int(argv[2]) if len(argv) > 2 else 8

    gateway = build_gateway()
    result = gateway.run_content_pipeline(season_code, round_number, top_n)

    print(
        f"Season {season_code} · Round {round_number}: "
        f"{result['matches_considered']} matches → "
        f"{result['content_generated']} content items"
    )
    if not result["items"]:
        print("  (no finalized matches for this round — nothing generated)")
        return 0

    output_dir = REPO_ROOT / "examples" / "content" / "live"
    output_dir.mkdir(parents=True, exist_ok=True)

    for item in result["items"]:
        svg = gateway.render_content_item(item["content_id"])
        fact_ok = "ok" if item["fact_validation"]["ok"] else "FAIL"
        visual_ok = "ok" if item["visual_validation"]["ok"] else "FAIL"
        print(
            f"  {item['story']['story_type']:<18} status={item['status']:<10} "
            f"priority={item['story']['priority']:<4} fact={fact_ok} visual={visual_ok}"
        )
        if svg and item["status"] == "approved":
            filename = f"{item['story']['story_type']}_{season_code}_R{round_number:02d}.svg"
            (output_dir / filename).write_text(svg, encoding="utf-8")
            print(f"      → wrote {filename}")

    print(f"\nApproved SVGs written to {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
