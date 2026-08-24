"""FEB Rating — the signature 0..10 performance mark.

Deterministic and versioned (never invented): computed from the boxscore line,
so it is reproducible and traceable like any other derived metric.

WHAT IT MEASURES, AND WHY IT IS NOT THE OFFICIAL VAL
----------------------------------------------------
The official FIBA valoración (which the FEB boxscore already publishes, and
which we ingest) measures ACCUMULATED PRODUCTION: play more minutes, produce
more, score a higher VAL. A *rating* has to answer a different question — how
well did this player perform — so it is normalised per 36 minutes. Measured on
real Segunda FEB data, a raw weighted-sum mark correlates 0.958 with VAL (i.e.
it is a rescaled duplicate of a number we already have); normalising by minutes
drops that to ~0.88 — still related, but carrying information VAL does not.

Small samples are shrunk toward the league rate (``_SHRINK_MINUTES`` minutes of
prior), so a good three-minute cameo cannot out-rate a full game, and lines
under ``MIN_MINUTES`` are not rated at all rather than rated on noise.

THE INPUTS (v2.1)
-----------------
v1 used only points/rebounds/assists/steals/blocks/turnovers, so it ignored
shooting efficiency entirely: 21 points on 8/25 scored exactly the same as 21
on 8/12. v2 adds the efficiency and discipline terms the public boxscore
already gives us — missed field goals, missed free throws, fouls committed —
plus a small three-point difficulty bonus. v2.1 adds fouls DRAWN, a real
contribution the boxscore records and v2.0 was discarding.

Not modelled, because the data does not exist in a final boxscore: clutch or
score-margin weighting, contested rebounds, shot contests (all need play-by-play
or tracking feeds). Offensive/defensive rebound splitting was measured and
rejected: it moved only 2 of the top 30 lines, which does not justify carrying
the extra field. A true-shooting term was measured and rejected too: against a
reference rating on a real game it matched the reference's ordering no better
than the miss penalties already do, and substituting it outright did worse —
and it double-counts efficiency the miss penalties already price in.

CALIBRATION (v2.1)
------------------
The curve is a logistic mapping the per-36 rate to a note. Unlike v1 — whose
constants were guessed from assumed magnitudes and, on real data, gave the
MEDIAN player a 5.7 and never reached beyond 8.2 — v2's two constants are
derived from the observed distribution of 595 real Segunda FEB player lines
(4 rounds, minutes >= MIN_MINUTES), anchoring the median at 6.5 and the 95th
percentile at 8.5:

    percentile  1  →  3.3      (a lost night)
    percentile  5  →  4.1
    percentile 25  →  5.5
    percentile 50  →  6.5      (an average game — the anchor)
    percentile 75  →  7.5
    percentile 90  →  8.1
    percentile 95  →  8.5
    percentile 99  →  9.1      (10 stays asymptotic, out of reach)

Bumping FEB_RATING_VERSION keeps historical content reproducible.
"""

from __future__ import annotations

import math
from typing import Optional

FEB_RATING_VERSION = "v2.1"

# A line shorter than this is not rated: too little to judge, and the note
# would be noise dressed as a verdict.
MIN_MINUTES = 10.0

# Impact weights.
_W_PTS, _W_REB, _W_AST, _W_STL, _W_BLK, _W_TO = 1.0, 1.2, 1.5, 2.0, 1.5, 1.0
_W_MISSED_FG = 0.8   # a missed field goal costs the team a possession
_W_MISSED_FT = 0.4   # a missed free throw is a cheaper, but real, waste
_W_FOUL = 0.3        # discipline
_W_THREE = 0.5       # difficulty bonus on top of the point the shot already scored
_W_FOUL_DRAWN = 0.5  # drawing contact is a real contribution (free throws, opponent
                     # foul trouble); the public boxscore records it and v2.0 dropped it

# Per-36 normalisation with shrinkage toward the league rate.
_LEAGUE_RATE = 0.602   # observed impact per minute across the sample
_SHRINK_MINUTES = 12.0
_PER = 36.0

# Logistic rate→note mapping, derived from the real distribution (see above).
_MID = 13.99
_STEEP = 0.0892


def impact_score(
    points: int, rebounds: int, assists: int,
    steals: int = 0, blocks: int = 0, turnovers: int = 0,
    *,
    field_goals_made: int = 0, field_goals_attempted: int = 0,
    free_throws_made: int = 0, free_throws_attempted: int = 0,
    three_points_made: int = 0, fouls: int = 0, fouls_received: int = 0,
) -> float:
    """Raw weighted impact of a boxscore line (not normalised by minutes)."""
    missed_fg = max(0, field_goals_attempted - field_goals_made)
    missed_ft = max(0, free_throws_attempted - free_throws_made)
    return (
        points * _W_PTS + rebounds * _W_REB + assists * _W_AST
        + steals * _W_STL + blocks * _W_BLK
        - turnovers * _W_TO
        - missed_fg * _W_MISSED_FG
        - missed_ft * _W_MISSED_FT
        - fouls * _W_FOUL
        + three_points_made * _W_THREE
        + fouls_received * _W_FOUL_DRAWN
    )


def feb_rating(
    points: int, rebounds: int, assists: int,
    steals: int = 0, blocks: int = 0, turnovers: int = 0,
    *,
    minutes: Optional[float] = None,
    field_goals_made: Optional[int] = None,
    field_goals_attempted: Optional[int] = None,
    free_throws_made: int = 0, free_throws_attempted: int = 0,
    three_points_made: int = 0, fouls: int = 0, fouls_received: int = 0,
) -> Optional[float]:
    """The FEB Rating (0..10, one decimal) for a single boxscore line.

    Returns ``None`` — never a fallback number — when the line cannot be rated
    on the same basis as every other: no minutes, fewer than ``MIN_MINUTES``
    played, or missing shooting data (rating a line without efficiency would
    silently produce a systematically higher, non-comparable note).
    """
    if minutes is None or minutes < MIN_MINUTES:
        return None
    if field_goals_made is None or field_goals_attempted is None:
        return None

    impact = impact_score(
        points, rebounds, assists, steals, blocks, turnovers,
        field_goals_made=field_goals_made,
        field_goals_attempted=field_goals_attempted,
        free_throws_made=free_throws_made,
        free_throws_attempted=free_throws_attempted,
        three_points_made=three_points_made,
        fouls=fouls,
        fouls_received=fouls_received,
    )
    # Per-36 rate, shrunk toward the league rate so short lines regress.
    rate = ((impact + _SHRINK_MINUTES * _LEAGUE_RATE) / (minutes + _SHRINK_MINUTES)) * _PER

    z = _STEEP * (rate - _MID)
    if z < -60:
        note = 0.0
    elif z > 60:
        note = 10.0
    else:
        note = 10.0 / (1.0 + math.exp(-z))
    return round(max(0.0, min(10.0, note)), 1)
