"""Story Object — the boundary between raw facts and editorial content.

A Story is what the Insight Engine detects. It carries only:
  - what kind of story it is (StoryType)
  - which entities it is about (player/team/round IDs)
  - the *facts* backing it (trace them to the data source)
  - a priority score assigned by the Content Planner
  - a template hint (which template can render this story type)

Stories carry NO copy, NO rendered image, NO channel. Those are downstream
concerns handled by the CopyGenerator, TemplateEngine and Publisher.

Rule: every field in ``facts`` MUST be traceable to a specific record in the
2aFEB_SCORE data platform. The Insight Engine never invents. The
CopyGenerator never invents. The FactValidator enforces the invariant.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional


class StoryType(str, Enum):
    # Match-level
    MATCH_FINAL = "match_final"
    BIGGEST_WIN = "biggest_win"
    CLOSEST_GAME = "closest_game"
    UPSET = "upset"
    COMEBACK = "comeback"

    # Player-level
    PLAYER_OF_ROUND = "player_of_round"
    TOP_SCORER = "top_scorer"
    TOP_REBOUNDER = "top_rebounder"
    TOP_ASSIST_PROVIDER = "top_assist_provider"
    BEST_PERFORMANCE = "best_performance"
    SEASON_HIGH = "season_high"
    DOUBLE_DOUBLE = "double_double"
    TRIPLE_DOUBLE = "triple_double"
    IRON_MAN = "iron_man"              # most minutes played (curious)
    SHARPSHOOTER = "sharpshooter"      # best 3-point game (shooting)
    PERFECT_NIGHT = "perfect_night"    # no misses from the field (shooting)
    PLAYMAKER = "playmaker"            # the round's assist leader (per-game director)
    DEFENSIVE_ANCHOR = "defensive_anchor"  # best defensive night: steals + blocks
    LONE_FLAG = "lone_flag"            # the season's only player from a country (bio)
    YOUNG_GUN = "young_gun"            # youngest player of the round with a real game (bio)
    VETERAN = "veteran"                # oldest player of the round with a real game (bio)
    BEST_FIVE = "best_five"            # the round's five best by FEB Rating (grid)
    BEST_FIVE_IDEAL = "best_five_ideal"  # the round's ideal five by position (court)
    CUSTOM_FIVE = "custom_five"        # a five the operator picked from a query
    CUSTOM_HERO = "custom_hero"        # a single-player hero card built from a query
    BEST_DUO = "best_duo"             # two teammates, best combined game (round)
    # Consecutive-game rachas ending in the current round (season scope). The
    # streak's length rides as the hero number, so the card frames how much of
    # a run this is — 4 partidos de 20+ seguidos, 3 dobles-dobles seguidos.
    PLAYER_STREAK_SCORING = "player_streak_scoring"
    PLAYER_STREAK_DD = "player_streak_dd"
    # Season-total leaders: total double-doubles / triple-doubles across the
    # season, not consecutive. Rendered on the same photo-hero layout as the
    # streak cards — a season-summary card, not a live streak.
    SEASON_DD_LEADER = "season_dd_leader"
    # TOP_SCORER / TOP_REBOUNDER / TOP_ASSIST_PROVIDER are the SEASON leaders.

    # Team-level
    TEAM_OF_ROUND = "team_of_round"
    WIN_STREAK = "win_streak"
    LOSS_STREAK = "loss_streak"
    POSITION_CHANGE = "position_change"
    LEADERBOARD_CHANGE = "leaderboard_change"

    # Round-level
    ROUND_RECAP = "round_recap"
    STAT_LEADERBOARD = "stat_leaderboard"

    # Editorial
    MILESTONE = "milestone"
    DID_YOU_KNOW = "did_you_know"


class StoryStatus(str, Enum):
    DETECTED = "detected"
    SELECTED = "selected"      # picked by planner
    REJECTED = "rejected"      # planner declined
    SUPERSEDED = "superseded"  # a better story of the same identity replaced it


# Which template can render each story type. A story with no mapping cannot
# be rendered — the pipeline refuses to proceed rather than pick a template
# arbitrarily.
STORY_TO_TEMPLATE: Dict[StoryType, str] = {
    StoryType.MATCH_FINAL: "match_final",
    StoryType.PLAYER_OF_ROUND: "player_of_round",
    StoryType.ROUND_RECAP: "round_recap",
    StoryType.STAT_LEADERBOARD: "stat_leaderboard",
    # Reuse existing templates for related story shapes (visual work deferred):
    StoryType.BIGGEST_WIN: "match_final",       # a scoreboard, framed as the rout
    StoryType.DOUBLE_DOUBLE: "player_of_round",  # a player card with their line
    StoryType.TRIPLE_DOUBLE: "player_of_round",
    StoryType.SEASON_HIGH: "player_of_round",    # a player card, framed as the high
    StoryType.UPSET: "match_final",              # a scoreboard, framed as the upset
    # Curious / shooting player angles — a player card framed by the hero stat
    # each detector chooses (assists, minutes, threes…), not always points.
    StoryType.PLAYMAKER: "player_of_round",
    StoryType.DEFENSIVE_ANCHOR: "player_of_round",
    StoryType.LONE_FLAG: "player_of_round",
    StoryType.YOUNG_GUN: "player_of_round",
    StoryType.VETERAN: "player_of_round",
    StoryType.BEST_FIVE: "best_five",
    # The operator's own query, rendered on the same grid. A separate type so
    # the automatic quinteto's novelty rule ("this round already has a
    # best_five") is not spent by a hand-made card, and so the queue says where
    # the card came from.
    StoryType.CUSTOM_FIVE: "best_five",
    # A hand-picked single player rendered on the photo-less hero layout.
    StoryType.CUSTOM_HERO: "stat_hero",
    StoryType.BEST_FIVE_IDEAL: "best_five_court",
    StoryType.IRON_MAN: "player_of_round",
    StoryType.SHARPSHOOTER: "player_of_round",
    StoryType.PERFECT_NIGHT: "player_of_round",
    # Season leaders (one card per category), framed by the leading season total.
    StoryType.TOP_SCORER: "player_of_round",
    StoryType.TOP_REBOUNDER: "player_of_round",
    StoryType.TOP_ASSIST_PROVIDER: "player_of_round",
    StoryType.WIN_STREAK: "team_streak",         # a team card: the run visualized
    StoryType.LOSS_STREAK: "team_streak",
    StoryType.BEST_DUO: "best_duo",              # two teammates + combined total
    # Player rachas: bespoke two-column card with the streak length as the
    # giant number on the left and the player photo bleeding down the right.
    StoryType.PLAYER_STREAK_SCORING: "player_streak",
    StoryType.PLAYER_STREAK_DD: "player_streak",
    # Season-total leaders reuse the same layout: the total DD count is the
    # giant number and the TD count rides as extras. Different story (not a
    # streak) but the same visual language works because both frame "one
    # player + one hero count".
    StoryType.SEASON_DD_LEADER: "player_streak",
}


# What each card CALLS ITSELF. Several story types share the player card, so
# without this every one of them fell back to the template's default and a
# triple-double announced itself as "Jugador de la jornada" with an MVP badge —
# the card lying about what it is. Declared per type here, in one place, so a new
# story type cannot silently inherit someone else's headline; a detector may
# still pass its own labels in the facts to override.
STORY_LABELS: Dict[StoryType, Dict[str, str]] = {
    StoryType.PLAYER_OF_ROUND: {"section": "Jugador de la jornada", "badge": "MVP"},
    StoryType.DOUBLE_DOUBLE: {"section": "Doble-doble", "badge": "DOBLE-DOBLE"},
    StoryType.TRIPLE_DOUBLE: {"section": "Triple-doble", "badge": "TRIPLE-DOBLE"},
    StoryType.SEASON_HIGH: {"section": "Máximo personal de la temporada",
                            "badge": "MÁXIMO"},
    StoryType.PLAYMAKER: {"section": "El director de juego", "badge": "DIRECTOR"},
    StoryType.DEFENSIVE_ANCHOR: {"section": "El muro de la jornada",
                                 "badge": "DEFENSA"},
    # The headline is overridden per card with the actual country ("El único de
    # BENIN"); this is the fallback, and the chip is dropped by the echo rule
    # whenever the country headline already contains "ÚNICO".
    StoryType.LONE_FLAG: {"section": "El único de su país", "badge": "ÚNICO"},
    StoryType.YOUNG_GUN: {"section": "La joven promesa", "badge": "PROMESA"},
    StoryType.VETERAN: {"section": "El veterano", "badge": "VETERANO"},
    StoryType.IRON_MAN: {"section": "El más trabajador", "badge": "MARATÓN"},
    StoryType.SHARPSHOOTER: {"section": "El tirador de la jornada", "badge": "SNIPER"},
    StoryType.PERFECT_NIGHT: {"section": "Noche perfecta", "badge": "SIN FALLO"},
    StoryType.TOP_SCORER: {"section": "Máximo anotador de la temporada",
                           "badge": "MÁX. ANOTADOR"},
    StoryType.TOP_REBOUNDER: {"section": "Máximo reboteador de la temporada",
                              "badge": "MÁX. REBOTES"},
    StoryType.TOP_ASSIST_PROVIDER: {"section": "Máximo asistente de la temporada",
                                    "badge": "MÁX. ASISTENCIAS"},
    # Consecutive-game rachas — one section per streak kind so a carousel of
    # both never repeats the same headline. The detector still overrides the
    # section per card with the actual "N PARTIDOS DE 20+ SEGUIDOS" claim.
    StoryType.PLAYER_STREAK_SCORING: {"section": "En racha anotadora",
                                      "badge": "RACHA VIVA"},
    StoryType.PLAYER_STREAK_DD: {"section": "En racha de dobles-dobles",
                                 "badge": "RACHA VIVA"},
    StoryType.SEASON_DD_LEADER: {"section": "Más dobles-dobles de la temporada",
                                 "badge": "MÁX. DD"},
}


# Human label for a story type, for the candidate chooser (where a card does not
# yet carry a section_label). Player-card types reuse their section from
# STORY_LABELS; these cover the rest.
STORY_DISPLAY_NAMES: Dict[str, str] = {
    "match_final": "Resultado del partido",
    "biggest_win": "Mayor paliza de la jornada",
    "closest_game": "El partido más ajustado",
    "stat_leaderboard": "Ranking de la jornada",
    "upset": "Sorpresa de la jornada",
    "win_streak": "Racha ganadora",
    "loss_streak": "Mala racha",
    "comeback": "Remontada",
    "best_duo": "El mejor dúo",
    "top_scorer": "Máximo anotador de la temporada",
    "top_rebounder": "Máximo reboteador de la temporada",
    "top_assist_provider": "Máximo asistente de la temporada",
    "best_five": "El quinteto de la jornada",
    "custom_five": "Quinteto a medida",
    "custom_hero": "Carta individual",
    "best_five_ideal": "El quinteto ideal (por posición)",
}


def display_name_for(story_type) -> str:
    """A readable Spanish label for any story type, for the chooser."""
    section = labels_for(story_type).get("section")
    if section:
        return section
    key = story_type.value if hasattr(story_type, "value") else str(story_type)
    return STORY_DISPLAY_NAMES.get(key, key)


def labels_for(story_type) -> Dict[str, str]:
    """Section + badge a card of this type should carry."""
    return STORY_LABELS.get(story_type, {"section": "", "badge": ""})


def _words(text: str) -> List[str]:
    """Comparison tokens: accent- and punctuation-free, upper case."""
    folded = unicodedata.normalize("NFKD", text or "")
    folded = "".join(c for c in folded if not unicodedata.combining(c))
    return [w for w in re.split(r"[^A-Za-z0-9]+", folded.upper()) if w]


def badge_echoes_headline(section: str, badge: str) -> bool:
    """True when the small chip on the portrait would only repeat the headline.

    A triple-double card headlined TRIPLE-DOBLE with a TRIPLE-DOBLE chip under
    the portrait says the same thing twice; the chip is meant to ADD a
    qualifier (MVP, SNIPER, SIN FALLO). Abbreviations count as repetition —
    "MÁX. ANOTADOR" adds nothing to "Máximo anotador de la temporada" — so a
    badge word matches when it merely PREFIXES a headline word.
    """
    head, chip = _words(section), _words(badge)
    if not chip:
        return False
    return all(any(h.startswith(w) for h in head) for w in chip)


@dataclass(frozen=True)
class StoryEntities:
    """The subjects a story is about. All optional — a round recap has none,
    a player story has player+team, a match story has home+away teams."""

    player_external_id: Optional[str] = None
    team_external_id: Optional[str] = None
    home_team_external_id: Optional[str] = None
    away_team_external_id: Optional[str] = None
    match_external_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass(frozen=True)
class StoryObject:
    """A detected story ready to be scored and (maybe) turned into content.

    Identity (see ``identity_key``) is deterministic on story_type + season +
    round + entities + a hash of the facts. Two runs of the pipeline over the
    same round produce the same identity for the same story — so the queue
    can deduplicate: never publish the same story twice.
    """

    story_type: StoryType
    season_code: str
    round_number: Optional[int]
    entities: StoryEntities
    facts: Dict[str, Any]
    source_refs: Dict[str, str]
    detected_at: datetime = field(default_factory=datetime.utcnow)
    status: StoryStatus = StoryStatus.DETECTED
    priority: int = 0

    @property
    def template_id(self) -> Optional[str]:
        # CUSTOM_HERO is one story ("hand-picked player + season stat") with
        # THREE visual variants that share the same facts: crest silhouette
        # (default, photo-less), photo hero (portrait-first), and split (giant
        # number left + photo bleeding down the right — the same layout the
        # season DD leader and the streaks use). The operator picks via a
        # facts.hero_style hint at create time so the queue dedup key stays
        # stable per (player, metric, style).
        if self.story_type == StoryType.CUSTOM_HERO:
            style = (self.facts or {}).get("hero_style")
            if style == "photo":
                return "stat_hero_photo"
            if style == "split":
                return "player_streak"
        return STORY_TO_TEMPLATE.get(self.story_type)

    @property
    def identity_key(self) -> str:
        """Stable identity for dedup: same story detected twice = same key."""
        payload = {
            "story_type": self.story_type.value,
            "season_code": self.season_code,
            "round_number": self.round_number,
            "entities": self.entities.to_dict(),
            "facts_hash": self.facts_hash,
        }
        blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]

    @property
    def facts_hash(self) -> str:
        """Hash of the facts payload — for detecting content drift on the
        same identity (e.g. a stat correction post-publish)."""
        blob = json.dumps(self.facts, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "story_type": self.story_type.value,
            "season_code": self.season_code,
            "round_number": self.round_number,
            "entities": self.entities.to_dict(),
            "facts": self.facts,
            "source_refs": self.source_refs,
            "detected_at": self.detected_at.isoformat(),
            "status": self.status.value,
            "priority": self.priority,
            "template_id": self.template_id,
            "identity_key": self.identity_key,
            "facts_hash": self.facts_hash,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "StoryObject":
        """Reconstruct a StoryObject from its ``to_dict`` form (persistence
        round-trip). Derived fields (template_id/identity_key/facts_hash) are
        recomputed, never read back."""
        return cls(
            story_type=StoryType(data["story_type"]),
            season_code=data["season_code"],
            round_number=data.get("round_number"),
            entities=StoryEntities(**data.get("entities", {})),
            facts=data.get("facts", {}),
            source_refs=data.get("source_refs", {}),
            detected_at=datetime.fromisoformat(data["detected_at"])
            if data.get("detected_at")
            else datetime.utcnow(),
            status=StoryStatus(data.get("status", StoryStatus.DETECTED.value)),
            priority=data.get("priority", 0),
        )
