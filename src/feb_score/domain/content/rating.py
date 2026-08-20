"""FEB Rating — the signature 0..10 performance mark.

Deterministic and versioned (never invented): computed from the boxscore line,
so it is reproducible and traceable like any other derived metric. It is NOT the
official FIBA valuation (VAL) — it's an editorial note on a 0..10 scale that
complements the raw stats and VAL.

v1.0 is PROVISIONAL: a transparent impact→note mapping centered near 6.0. The
weighting/curve is meant to be tuned (most real games land ~5.5+, so the useful
range is compressed) — that refinement is tracked separately and will bump the
version. Bumping FEB_RATING_VERSION keeps historical content reproducible.
"""

from __future__ import annotations

FEB_RATING_VERSION = "v1.0-provisional"

# Impact weights (same family as the existing player impact score).
_W_PTS, _W_REB, _W_AST, _W_STL, _W_BLK, _W_TO = 1.0, 1.2, 1.5, 2.0, 1.5, 1.0

# Linear impact→note mapping: note = BASE + impact * SLOPE, clamped to [0, 10].
# Tuned so scores spread across the useful band instead of saturating at 10:
# a quiet game (impact ~8) → ~5.6; a solid game (impact ~30) → ~7.4; a huge
# game (impact ~50) → ~9.0. Provisional — the curve is the thing to revisit.
_BASE, _SLOPE = 5.0, 0.08


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
    note = _BASE + impact_score(points, rebounds, assists, steals, blocks, turnovers) * _SLOPE
    return round(max(0.0, min(10.0, note)), 1)
