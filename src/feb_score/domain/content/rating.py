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

FEB_RATING_VERSION = "3.0"

# --- v3.0 (supersedes v2.1) --------------------------------------------------
# Three structural changes:
#   1. SHRINKAGE toward the league rate is stronger (20, up from 12), so a short
#      hot stint can no longer masquerade statistically as a full game.
#   2. EFFICIENCY is a true-shooting term vs the league median, REPLACING v2.1's
#      raw miss penalties (which double-counted the same efficiency).
#   3. CALIBRATION is a FROZEN percentile map fitted ONCE on the 4-season pool
#      (2022-23..2025-26, 22,431 rateable lines): the rate->note curve below is
#      fixed and versioned, so a 9,2 means the same thing every season. A
#      continuous CONFIDENCE factor then regresses low-sample notes toward 6.5.
# Rating (how good the game was) is deliberately separate from ELIGIBILITY (how
# far we trust it for rankings): see feb_confidence_tier / RANKING_MIN_MINUTES.
# NEVER recompute the frozen constants silently — bump FEB_RATING_VERSION, so
# already-published content stays reproducible.

MIN_MINUTES = 10.0            # a shorter line is not rated at all (noise)
RANKING_MIN_MINUTES = 15.0    # ...but a leaderboard/award should demand more

# Impact weights (possession value; unchanged from v2.1 except the miss
# penalties, now folded into the efficiency term).
_W_PTS, _W_REB, _W_AST, _W_STL, _W_BLK, _W_TO = 1.0, 1.2, 1.5, 2.0, 1.5, 1.0
_W_FOUL = 0.3
_W_THREE = 0.5        # difficulty premium on top of the point the shot scored
_W_FOUL_DRAWN = 0.5

# Efficiency: true shooting vs the league median, scaled by shot volume. Frozen.
_TS_LEAGUE = 0.5112
_EFF_W = 1.6

# Per-36 with shrinkage toward the league impact rate. Frozen on the pool.
_LEAGUE_RATE = 0.7259
_SHRINK_MINUTES = 20.0
_PER = 36.0

# FROZEN calibration: per-36 rate -> note, fitted on the 4-season pool at the
# target percentiles (median 6.5; 9.5+ ~ top 0.15%; 10 beyond anything observed).
_CALIBRATION = (
    (12.250, 3.6), (14.097, 4.2), (15.393, 4.7), (17.300, 5.8),
    (21.014, 6.1), (25.789, 6.5), (29.845, 6.9), (34.062, 7.4),
    (37.193, 7.9), (41.699, 8.4), (46.267, 8.9), (49.016, 9.2),
    (52.319, 9.6), (57.257, 9.8), (69.220, 9.95),
)


def _true_shooting(points: int, fga: int, fta: int) -> Optional[float]:
    shots = 2.0 * (fga + 0.44 * fta)
    return (points / shots) if shots > 0 else None


def impact_score(
    points: int, rebounds: int, assists: int,
    steals: int = 0, blocks: int = 0, turnovers: int = 0,
    *,
    field_goals_made: int = 0, field_goals_attempted: int = 0,
    free_throws_made: int = 0, free_throws_attempted: int = 0,
    three_points_made: int = 0, fouls: int = 0, fouls_received: int = 0,
) -> float:
    """Raw weighted impact of a line (v3.0): possession-value box score plus a
    true-shooting term vs the league, NOT normalised by minutes. The efficiency
    term replaces v2.1's raw missed-shot penalties, which double-counted it."""
    impact = (
        points * _W_PTS + rebounds * _W_REB + assists * _W_AST
        + steals * _W_STL + blocks * _W_BLK
        - turnovers * _W_TO - fouls * _W_FOUL
        + three_points_made * _W_THREE + fouls_received * _W_FOUL_DRAWN
    )
    ts = _true_shooting(points, field_goals_attempted, free_throws_attempted)
    if ts is not None:
        volume = field_goals_attempted + 0.44 * free_throws_attempted
        impact += (ts - _TS_LEAGUE) * volume * _EFF_W
    return impact


def _calibrate(rate: float) -> float:
    """Map a per-36 rate to a 0..10 note through the frozen percentile curve —
    piecewise linear, extrapolated past the ends so 10 stays reachable only by a
    line beyond anything seen in four seasons (and 0 only by a catastrophic one)."""
    pts = _CALIBRATION
    if rate <= pts[0][0]:
        (r0, n0), (r1, n1) = pts[0], pts[1]
    elif rate >= pts[-1][0]:
        (r0, n0), (r1, n1) = pts[-2], pts[-1]
    else:
        (r0, n0), (r1, n1) = pts[0], pts[1]
        for i in range(1, len(pts)):
            if rate < pts[i][0]:
                (r0, n0), (r1, n1) = pts[i - 1], pts[i]
                break
    note = n0 + (n1 - n0) * (rate - r0) / (r1 - r0)
    return max(0.0, min(10.0, note))


def _confidence(minutes: float) -> float:
    """Continuous sample-confidence in [0,1]: ~0.58 at 10', ~0.82 at 20', 1.0 at
    30'+. Regresses a low-sample note toward the mean, both ways, no hard cutoff."""
    return min(1.0, math.sqrt(minutes / _PER * (_PER / 30.0)))  # sqrt(minutes/30)


def feb_confidence_tier(minutes: Optional[float]) -> str:
    """How far a note can be trusted for RANKINGS — separate from the note
    itself. A great 12-minute game still gets a real rating; it just is not
    'high' confidence. 'low' lines are kept out of leaderboards/awards."""
    if minutes is None or minutes < MIN_MINUTES:
        return "none"
    if minutes >= 25.0:
        return "high"
    if minutes >= RANKING_MIN_MINUTES:
        return "medium"
    return "low"


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
    """The FEB Rating (0..10, one decimal) for a single boxscore line — v3.0.

    Returns ``None`` — never a fallback number — when the line cannot be graded
    on the same basis as every other: no minutes, under ``MIN_MINUTES``, or no
    shooting data. Pipeline: impact -> per-36 with shrinkage -> frozen percentile
    map -> continuous confidence regression toward 6.5.
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
    rate = ((impact + _SHRINK_MINUTES * _LEAGUE_RATE) / (minutes + _SHRINK_MINUTES)) * _PER
    note = _calibrate(rate)
    note = 6.5 + (note - 6.5) * _confidence(minutes)
    return round(max(0.0, min(10.0, note)), 1)
