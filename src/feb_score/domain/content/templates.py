"""Template contracts — the slot requirements each template promises.

Templates are files (SVG) but their DATA CONTRACT lives here in the domain.
The VisualValidator uses these to reject content items whose data does not
fill every required slot. Optional slots may be missing without failing
validation.

Slots are dotted paths into the data dict the renderer receives.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Tuple


TEMPLATE_VERSION = "1.0"


@dataclass(frozen=True)
class TemplateContract:
    template_id: str
    version: str
    canvas: str          # "IG_PORTRAIT" | "IG_POST" | "IG_STORY"
    required_slots: Tuple[str, ...]
    optional_slots: Tuple[str, ...] = ()


# Slot policy (robustness): a slot is REQUIRED only when the template cannot
# render meaningfully without it. Anything that a real (imperfect) FEB feed can
# legitimately omit — a team/player display name, a top scorer when no boxscore
# rows exist — is OPTIONAL and resolved to a graceful fallback by the pipeline
# (``display.*`` = catalog name OR external_id; a missing top scorer collapses
# to "—"). This keeps a round producing content even when the catalog is not
# fully populated (documented behavior of the data platform).
TEMPLATES: Dict[str, TemplateContract] = {
    "best_five": TemplateContract(
        template_id="best_five",
        version=TEMPLATE_VERSION,
        canvas="IG_PORTRAIT",
        required_slots=(
            "story.facts.lineup",
        ),
    ),
    "best_five_court": TemplateContract(
        template_id="best_five_court",
        version=TEMPLATE_VERSION,
        canvas="IG_PORTRAIT",
        required_slots=(
            "story.facts.lineup",
        ),
    ),
    "match_final": TemplateContract(
        template_id="match_final",
        version=TEMPLATE_VERSION,
        canvas="IG_PORTRAIT",
        required_slots=(
            "story.round_number",
            "story.facts.home_score",
            "story.facts.away_score",
            "display.home_team",
            "display.away_team",
            "copy.headline",
            "copy.subtitle",
        ),
        optional_slots=(
            "assets.home_team_color",
            "assets.away_team_color",
        ),
    ),
    "player_of_round": TemplateContract(
        template_id="player_of_round",
        version=TEMPLATE_VERSION,
        canvas="IG_PORTRAIT",
        required_slots=(
            "story.round_number",
            "story.facts.points",
            "story.facts.rebounds",
            "story.facts.assists",
            "story.facts.impact_score",
            "display.player",
            "copy.headline",
            "copy.subtitle",
        ),
        optional_slots=(
            "display.team",
            "assets.player_initials",
            "assets.team_color",
        ),
    ),
    "round_recap": TemplateContract(
        template_id="round_recap",
        version=TEMPLATE_VERSION,
        canvas="IG_PORTRAIT",
        required_slots=(
            "story.round_number",
            "story.facts.matches_played",
            "story.facts.biggest_win_margin",
            "story.facts.closest_game_margin",
            "copy.headline",
            "copy.subtitle",
        ),
        optional_slots=(
            "display.top_scorer",
            "display.biggest_win_team",
        ),
    ),
    "stat_leaderboard": TemplateContract(
        template_id="stat_leaderboard",
        version=TEMPLATE_VERSION,
        canvas="IG_PORTRAIT",
        required_slots=(
            "story.round_number",
            "story.facts.leaders",
            "copy.headline",
            "copy.subtitle",
        ),
        optional_slots=(),
    ),
    "best_duo": TemplateContract(
        template_id="best_duo",
        version=TEMPLATE_VERSION,
        canvas="IG_PORTRAIT",
        required_slots=(
            "story.round_number",
            "story.facts.p1_points",
            "story.facts.p2_points",
            "story.facts.combined_points",
            "copy.headline",
            "copy.subtitle",
        ),
        optional_slots=(
            "story.facts.p1_name",
            "story.facts.p2_name",
            "story.facts.team_name",
        ),
    ),
    "team_streak": TemplateContract(
        template_id="team_streak",
        version=TEMPLATE_VERSION,
        canvas="IG_PORTRAIT",
        required_slots=(
            "story.round_number",
            "story.facts.streak_kind",
            "story.facts.streak_length",
            "copy.headline",
            "copy.subtitle",
        ),
        optional_slots=(
            "story.facts.team_name",
            "assets.team_crest",
        ),
    ),
}
