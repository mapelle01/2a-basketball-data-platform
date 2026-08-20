"""FEB Rating — the signature 0..10 performance mark.

Deterministic and versioned (never invented): computed from the boxscore line,
so it is reproducible and traceable like any other derived metric. It is NOT the
official FIBA valuation (VAL) — it's an editorial note on a 0..10 scale that
complements the raw stats and VAL.

Curve (v1.1). The raw ``impact_score`` is mapped to a note with a LOGISTIC
(sigmoid), not a line. This fixes the two flaws of the v1 linear map:
  * a hard floor at 5.0 killed the whole 0..5 band (everyone landed 5.5+);
  * it reached 10 too easily (impact ~62), so every big game flattened to a
    dull 10 with no separation among the elite.
The sigmoid instead sits an AVERAGE game near ~6.5, keeps the low band alive (a
poor game reads ~4), and makes 10 asymptotic — reserved for a historic line,
never handed out for a merely great one. Calibrated to Segunda FEB impact
magnitudes (a rotation game ~18, a starter ~28, a star game ~44, a monster ~58):

    impact   0 →  3.9      (nothing / a lost night)
    impact  15 →  5.7      (below average)
    impact  22 →  6.5      (an average game — the anchor)
    impact  30 →  7.3      (solid)
    impact  40 →  8.2      (strong)
    impact  55 →  9.0      (huge)
    impact  75 →  9.6      (historic — 10 stays out of reach)

Still PROVISIONAL: the weights and the anchor are transparent constants meant to
be tuned against real distributions. Bumping FEB_RATING_VERSION keeps historical
content reproducible.
"""

from __future__ import annotations

import math

FEB_RATING_VERSION = "v1.1-provisional"

# Impact weights (same family as the existing player impact score).
_W_PTS, _W_REB, _W_AST, _W_STL, _W_BLK, _W_TO = 1.0, 1.2, 1.5, 2.0, 1.5, 1.0

# Logistic impact→note mapping: note = 10 / (1 + exp(-STEEP * (impact - MID))).
# MID is the impact that scores exactly 5.0 (the sigmoid's inflection); STEEP is
# how sharply the note rises through the common band. Chosen so an average game
# (impact ~22) lands ~6.5 and a strong one (~40) ~8.2, with 10 asymptotic.
_MID = 9.0
_STEEP = 0.048


def impact_score(
    points: int, rebounds: int, assists: int,
    steals: int = 0, blocks: int = 0, turnovers: int = 0,
) -> float:
    return (
        points * _W_PTS + rebounds * _W_REB + assists * _W_AST
        + steals * _W_STL + blocks * _W_BLK - turnovers * _W_TO
    )


def feb_rating(
    points: int, rebounds: int, assists: int,
    steals: int = 0, blocks: int = 0, turnovers: int = 0,
) -> float:
    """The FEB Rating (0..10, one decimal) for a single boxscore line."""
    impact = impact_score(points, rebounds, assists, steals, blocks, turnovers)
    # Guard the exp against overflow for extreme (unrealistic) impacts.
    z = _STEEP * (impact - _MID)
    if z < -60:
        note = 0.0
    elif z > 60:
        note = 10.0
    else:
        note = 10.0 / (1.0 + math.exp(-z))
    return round(max(0.0, min(10.0, note)), 1)
