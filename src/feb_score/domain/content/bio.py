"""Roster attributes — the BIO lane's input.

Every detector until now read a boxscore, so every card said the same kind of
thing: who was best at a column this round. The bio backfill has been sitting
in production unused; this is what lets a card say something a scoreboard
cannot.

SCOPE NOTE: only nationality is carried. Birth date and height are populated
too, but a lane is added when a detector needs it — not in advance.

TRUTH NOTE: the federation publishes ONE nationality per player. A dual
national appears under whichever the FEB recorded, so a claim built on this is
"the only player the FEB registers as X", not a statement about passports. The
copy says "de la liga" rather than anything stronger for that reason.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Dict, Mapping, Optional


@dataclass(frozen=True)
class LeagueBio:
    """Who is from where, for ONE season, plus how common each country is.

    Season-wide by construction: "the only player from Benin" is a claim about
    the whole league, so counting within a round would make it false.
    """

    nationality_by_player: Mapping[str, str] = field(default_factory=dict)

    def nationality(self, player_external_id: str) -> Optional[str]:
        return self.nationality_by_player.get(player_external_id)

    def _counts(self) -> Dict[str, int]:
        # Small (a few hundred players) and rebuilt per run, so counting on
        # demand costs nothing and keeps the dataclass frozen and hashable.
        return Counter(self.nationality_by_player.values())

    def countrymen(self, player_external_id: str) -> Optional[int]:
        """How many players in the season share this player's nationality
        (including them). None when the player has no nationality on record —
        absence is not evidence of rarity."""
        nat = self.nationality(player_external_id)
        if not nat:
            return None
        return self._counts().get(nat, 0)

    def is_sole_representative(self, player_external_id: str) -> bool:
        return self.countrymen(player_external_id) == 1

    @property
    def countries(self) -> int:
        return len(self._counts())

    def __bool__(self) -> bool:
        return bool(self.nationality_by_player)
