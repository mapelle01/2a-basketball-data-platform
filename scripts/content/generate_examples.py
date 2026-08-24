"""Generate 3 reference content pieces for the Segunda FEB 2025-2026 season.

Runs the full pipeline (Insight → Planner → Copy → Render → Validate →
Queue) against realistic fixture data shaped like the 2aFEB_SCORE data
platform's read models. Every fact in the resulting SVGs traces to the
input DTOs — no LLM, no hallucinations.

Output: examples/content/*.svg + a manifest.json with pipeline metadata.

Usage:
    python -m scripts.content.generate_examples
    # or
    .venv/bin/python scripts/content/generate_examples.py
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

# Allow running as a plain script from the repo root.
REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from feb_score.application.use_cases.round_pipeline import RoundPipeline  # noqa: E402
from feb_score.domain.content.insights import MatchFactsInput, PlayerLineInput  # noqa: E402
from feb_score.infrastructure.rendering.asset_provider import StatisticalAssetProvider  # noqa: E402
from feb_score.infrastructure.rendering.design_system import DESIGN_SYSTEM_VERSION  # noqa: E402
from feb_score.infrastructure.rendering.svg_renderer import ComponentSvgRenderer  # noqa: E402


# ---------------------------------------------------------------------------
# Fixture — round 12 of Segunda FEB 2025-2026.
# Shapes and id formats match the real data platform. Values are realistic
# but not tied to any specific real match — this is the reference sample.
# ---------------------------------------------------------------------------

SEASON = "2025-2026"
ROUND = 12

MATCHES = [
    MatchFactsInput(
        external_id="feb_match_2025_2026_R12_M01",
        season_code=SEASON,
        round_number=ROUND,
        home_team_external_id="979897",
        away_team_external_id="983412",
        home_team_name="Basket Navarra",
        away_team_name="CB Prat",
        home_score=88,
        away_score=76,
        scheduled_at=datetime(2026, 1, 24, 18, 0),
    ),
    MatchFactsInput(
        external_id="feb_match_2025_2026_R12_M02",
        season_code=SEASON,
        round_number=ROUND,
        home_team_external_id="971203",
        away_team_external_id="984501",
        home_team_name="Fibwi Palma",
        away_team_name="Coviran Granada B",
        home_score=79,
        away_score=95,
        scheduled_at=datetime(2026, 1, 24, 19, 0),
    ),
    MatchFactsInput(
        external_id="feb_match_2025_2026_R12_M03",
        season_code=SEASON,
        round_number=ROUND,
        home_team_external_id="977845",
        away_team_external_id="972199",
        home_team_name="CB Salou",
        away_team_name="Amics Castelló",
        home_score=71,
        away_score=69,
        scheduled_at=datetime(2026, 1, 25, 12, 30),
    ),
    MatchFactsInput(
        external_id="feb_match_2025_2026_R12_M04",
        season_code=SEASON,
        round_number=ROUND,
        home_team_external_id="989002",
        away_team_external_id="967421",
        home_team_name="Alicante Cimarrones",
        away_team_name="Melilla Baloncesto",
        home_score=104,
        away_score=72,
        scheduled_at=datetime(2026, 1, 25, 18, 0),
    ),
]

PLAYER_LINES = [
    PlayerLineInput(
        player_external_id="2772828",
        player_name="F. Andrade Amiel",
        team_external_id="979897",
        team_name="Basket Navarra",
        match_external_id="feb_match_2025_2026_R12_M01",
        points=27, rebounds=8, assists=6, steals=2, blocks=1, turnovers=3, minutes=32.4,
    ),
    PlayerLineInput(
        player_external_id="2818401",
        player_name="J. Molina",
        team_external_id="983412",
        team_name="CB Prat",
        match_external_id="feb_match_2025_2026_R12_M01",
        points=19, rebounds=5, assists=4, steals=1, blocks=0, turnovers=2, minutes=28.1,
    ),
    PlayerLineInput(
        player_external_id="2799112",
        player_name="A. Bogdanović",
        team_external_id="984501",
        team_name="Coviran Granada B",
        match_external_id="feb_match_2025_2026_R12_M02",
        points=24, rebounds=11, assists=3, steals=2, blocks=2, turnovers=1, minutes=30.0,
    ),
    PlayerLineInput(
        player_external_id="2801077",
        player_name="M. Cuevas",
        team_external_id="971203",
        team_name="Fibwi Palma",
        match_external_id="feb_match_2025_2026_R12_M02",
        points=22, rebounds=4, assists=7, steals=1, blocks=0, turnovers=4, minutes=31.2,
    ),
    PlayerLineInput(
        player_external_id="2822559",
        player_name="D. Fernández",
        team_external_id="977845",
        team_name="CB Salou",
        match_external_id="feb_match_2025_2026_R12_M03",
        points=18, rebounds=6, assists=8, steals=3, blocks=0, turnovers=2, minutes=34.6,
    ),
    PlayerLineInput(
        player_external_id="2812203",
        player_name="C. Sáez",
        team_external_id="989002",
        team_name="Alicante Cimarrones",
        match_external_id="feb_match_2025_2026_R12_M04",
        points=31, rebounds=9, assists=5, steals=2, blocks=1, turnovers=2, minutes=29.8,
    ),
    PlayerLineInput(
        player_external_id="2831190",
        player_name="K. Toure",
        team_external_id="967421",
        team_name="Melilla Baloncesto",
        match_external_id="feb_match_2025_2026_R12_M04",
        points=21, rebounds=7, assists=3, steals=0, blocks=1, turnovers=3, minutes=30.4,
    ),
]


def main() -> int:
    output_dir = REPO_ROOT / "examples" / "content"
    output_dir.mkdir(parents=True, exist_ok=True)

    pipeline = RoundPipeline(
        renderer=ComponentSvgRenderer(),
        assets=StatisticalAssetProvider(),
        design_system_version=DESIGN_SYSTEM_VERSION,
    )

    items = pipeline.run(SEASON, ROUND, MATCHES, PLAYER_LINES, top_n=8).items

    # Pick one representative content per story type so the deliverable is
    # exactly the 3 references the design system was built for.
    by_type = {}
    for item in items:
        st = item.story.story_type.value
        if st not in by_type or item.story.priority > by_type[st].story.priority:
            by_type[st] = item

    wanted = ["match_final", "player_of_round", "round_recap"]
    manifest = {
        "season_code": SEASON,
        "round_number": ROUND,
        "generated_at": datetime.utcnow().isoformat(),
        "design_system_version": items[0].design_system_version if items else None,
        "items": [],
    }

    for st in wanted:
        item = by_type.get(st)
        if item is None or item.rendered_svg is None:
            print(f"[warn] no content produced for {st}")
            continue
        filename = f"{st}_{SEASON}_R{ROUND:02d}.svg"
        (output_dir / filename).write_text(item.rendered_svg, encoding="utf-8")

        manifest["items"].append({
            "story_type": st,
            "filename": filename,
            "content_id": item.content_id,
            "status": item.status.value,
            "priority": item.story.priority,
            "fact_validation_ok": item.fact_validation["ok"] if item.fact_validation else None,
            "visual_validation_ok": item.visual_validation["ok"] if item.visual_validation else None,
            "identity_key": item.story.identity_key,
            "copy": item.copy,
            "story": item.story.to_dict(),
        })

    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print(f"Wrote {len(manifest['items'])} content pieces to {output_dir}")
    for entry in manifest["items"]:
        fact_ok = "ok" if entry["fact_validation_ok"] else "FAIL"
        visual_ok = "ok" if entry["visual_validation_ok"] else "FAIL"
        print(
            f"  {entry['filename']:<55} status={entry['status']:<10} "
            f"priority={entry['priority']:<4} fact={fact_ok} visual={visual_ok}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
