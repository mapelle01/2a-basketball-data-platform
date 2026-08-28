"""Roster attributes — the BIO lane's input.

Every detector until now read a boxscore, so every card said the same kind of
thing: who was best at a column this round. The bio backfill has been sitting
in production unused; this is what lets a card say something a scoreboard
cannot.

SCOPE NOTE: nationality and birth date are carried. Height is populated too,
but a lane is added when a detector needs it — not in advance.

TRUTH NOTE: the federation publishes ONE nationality per player. A dual
national appears under whichever the FEB recorded, so a claim built on this is
"the only player the FEB registers as X", not a statement about passports. The
copy says "de la liga" rather than anything stronger for that reason.

AGE is computed against the ROUND's date (never "today"), so a backfilled card
states the player's age as it was that night — truthful and stable, not a
figure that drifts every time the card is re-rendered.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
import unicodedata
from datetime import date
from typing import Dict, Mapping, Optional


# The five canonical court positions, in the order the court template places
# them (pívot at the top, then the two forwards, then the two guards).
POSITIONS = ("Pívot", "A-Pívot", "Alero", "Base", "Escolta")


def normalize_position(raw: Optional[str]) -> Optional[str]:
    """Fold the FEB's Puesto field to one of the five canonical positions, or
    None when it is missing ("-") or unrecognised. The federation writes it
    several ways — A-Pivot / A-pívot / A_Pívot / Ala-Pívot, and a typo'd Esolta —
    so it is stripped of accents and separators before matching."""
    if not raw:
        return None
    folded = unicodedata.normalize("NFKD", raw)
    token = "".join(c for c in folded if not unicodedata.combining(c))
    token = "".join(c for c in token.upper() if c.isalnum())
    if token in ("APIVOT", "ALAPIVOT"):
        return "A-Pívot"
    if token == "PIVOT":
        return "Pívot"
    if token == "BASE":
        return "Base"
    if token in ("ESCOLTA", "ESOLTA"):
        return "Escolta"
    if token == "ALERO":
        return "Alero"
    return None


@dataclass(frozen=True)
class LeagueBio:
    """Roster attributes for ONE season: nationality (with league-wide counts)
    and birth date (for age).

    Season-wide by construction: "the only player from Benin" is a claim about
    the whole league, so counting within a round would make it false.
    """

    nationality_by_player: Mapping[str, str] = field(default_factory=dict)
    birth_by_player: Mapping[str, str] = field(default_factory=dict)
    position_by_player: Mapping[str, str] = field(default_factory=dict)

    def nationality(self, player_external_id: str) -> Optional[str]:
        return self.nationality_by_player.get(player_external_id)

    def position(self, player_external_id: str) -> Optional[str]:
        """Canonical court position, or None if unknown."""
        return self.position_by_player.get(player_external_id)

    def age_on(self, player_external_id: str, reference: date) -> Optional[int]:
        """Full years old on ``reference``, or None if no birth date is on
        record or it cannot be parsed. Absence yields None — never a guess."""
        raw = self.birth_by_player.get(player_external_id)
        if not raw:
            return None
        try:
            y, m, d = (int(x) for x in raw[:10].split("-"))
            born = date(y, m, d)
        except (ValueError, TypeError):
            return None
        return reference.year - born.year - (
            (reference.month, reference.day) < (born.month, born.day)
        )

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
        return bool(self.nationality_by_player or self.birth_by_player
                    or self.position_by_player)
