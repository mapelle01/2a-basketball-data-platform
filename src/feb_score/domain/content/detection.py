from __future__ import annotations

from typing import List, Tuple

from .model import (
    ContentPriority,
    Highlight,
    HighlightType,
    MatchFacts,
    PlayerLine,
    TeamLine,
)


BLOWOUT_MARGIN = 20
CLOSE_GAME_MARGIN = 5
HIGH_SCORING_TOTAL = 170
LOW_SCORING_TOTAL = 120
THIRTY_PLUS_THRESHOLD = 30
TWENTY_PLUS_THRESHOLD = 20
SHOOTING_DISPLAY_PCT = 0.60
BLOCK_PARTY_THRESHOLD = 4
ASSIST_LEADER_THRESHOLD = 8
REBOUND_KING_THRESHOLD = 12


def detect_match_highlights(
    facts: MatchFacts,
    player_lines: Tuple[PlayerLine, ...],
    home_team: TeamLine,
    away_team: TeamLine,
) -> List[Highlight]:
    highlights: List[Highlight] = []
    highlights.extend(_detect_game_character(facts))
    highlights.extend(_detect_player_performances(player_lines))
    highlights.extend(_detect_team_shooting(home_team, away_team))
    return highlights


def compute_priority(facts: MatchFacts, highlights: List[Highlight]) -> ContentPriority:
    has = {h.highlight_type for h in highlights}

    if HighlightType.TRIPLE_DOUBLE in has or HighlightType.OVERTIME in has:
        return ContentPriority.URGENT

    if HighlightType.THIRTY_PLUS in has or HighlightType.CLOSE_GAME in has:
        return ContentPriority.HIGH

    if HighlightType.BLOWOUT in has or HighlightType.DOUBLE_DOUBLE in has:
        return ContentPriority.NORMAL

    return ContentPriority.LOW


def generate_headline(facts: MatchFacts, highlights: List[Highlight]) -> str:
    has = {h.highlight_type for h in highlights}
    score = f"{facts.home_score}-{facts.away_score}"

    if HighlightType.OVERTIME in has:
        return f"Overtime thriller! {score}"

    if HighlightType.CLOSE_GAME in has:
        return f"Nailbiter: {score}"

    if HighlightType.BLOWOUT in has:
        return f"Dominant win: {score}"

    return f"Final: {score}"


def generate_subheadline(
    facts: MatchFacts,
    highlights: List[Highlight],
    player_lines: Tuple[PlayerLine, ...],
) -> str:
    top_scorers = [h for h in highlights if h.highlight_type == HighlightType.TOP_SCORER]
    special = [
        h for h in highlights
        if h.highlight_type in {
            HighlightType.TRIPLE_DOUBLE,
            HighlightType.THIRTY_PLUS,
            HighlightType.DOUBLE_DOUBLE,
        }
    ]

    if special:
        best = special[0]
        return f"{best.subject_id}: {best.label}"

    if top_scorers:
        ts = top_scorers[0]
        return f"Top scorer: {ts.subject_id} ({int(ts.value)} pts)"

    if player_lines:
        best = max(player_lines, key=lambda p: p.points)
        return f"Top scorer: {best.player_external_id} ({best.points} pts)"

    return f"Round {facts.round_number}"


# ---------------------------------------------------------------------------
# Internal detection functions
# ---------------------------------------------------------------------------


def _detect_game_character(facts: MatchFacts) -> List[Highlight]:
    highlights: List[Highlight] = []

    if facts.margin <= CLOSE_GAME_MARGIN:
        highlights.append(Highlight(
            highlight_type=HighlightType.CLOSE_GAME,
            subject_id=facts.match_external_id,
            subject_type="match",
            value=float(facts.margin),
            label=f"Decided by {facts.margin} points",
        ))

    if facts.margin >= BLOWOUT_MARGIN:
        highlights.append(Highlight(
            highlight_type=HighlightType.BLOWOUT,
            subject_id=facts.winner_id,
            subject_type="team",
            value=float(facts.margin),
            label=f"Won by {facts.margin} points",
        ))

    if facts.total_points >= HIGH_SCORING_TOTAL:
        highlights.append(Highlight(
            highlight_type=HighlightType.HIGH_SCORING,
            subject_id=facts.match_external_id,
            subject_type="match",
            value=float(facts.total_points),
            label=f"{facts.total_points} total points",
        ))

    if facts.total_points <= LOW_SCORING_TOTAL:
        highlights.append(Highlight(
            highlight_type=HighlightType.LOW_SCORING,
            subject_id=facts.match_external_id,
            subject_type="match",
            value=float(facts.total_points),
            label=f"Low-scoring affair: {facts.total_points} total",
        ))

    if len(facts.periods) > 4:
        highlights.append(Highlight(
            highlight_type=HighlightType.OVERTIME,
            subject_id=facts.match_external_id,
            subject_type="match",
            value=float(len(facts.periods) - 4),
            label=f"Went to {'double ' if len(facts.periods) > 5 else ''}overtime",
        ))

    return highlights


def _detect_player_performances(player_lines: Tuple[PlayerLine, ...]) -> List[Highlight]:
    highlights: List[Highlight] = []
    if not player_lines:
        return highlights

    top = max(player_lines, key=lambda p: p.points)
    highlights.append(Highlight(
        highlight_type=HighlightType.TOP_SCORER,
        subject_id=top.player_external_id,
        subject_type="player",
        value=float(top.points),
        label=f"{top.points} pts",
    ))

    for p in player_lines:
        doubles = sum(1 for v in (p.points, p.rebounds, p.assists, p.steals, p.blocks) if v >= 10)

        if doubles >= 3:
            highlights.append(Highlight(
                highlight_type=HighlightType.TRIPLE_DOUBLE,
                subject_id=p.player_external_id,
                subject_type="player",
                value=float(doubles),
                label=f"{p.points}p/{p.rebounds}r/{p.assists}a",
            ))
        elif doubles >= 2:
            highlights.append(Highlight(
                highlight_type=HighlightType.DOUBLE_DOUBLE,
                subject_id=p.player_external_id,
                subject_type="player",
                value=float(doubles),
                label=f"{p.points}p/{p.rebounds}r/{p.assists}a",
            ))

        if p.points >= THIRTY_PLUS_THRESHOLD:
            highlights.append(Highlight(
                highlight_type=HighlightType.THIRTY_PLUS,
                subject_id=p.player_external_id,
                subject_type="player",
                value=float(p.points),
                label=f"{p.points}-point explosion",
            ))
        elif p.points >= TWENTY_PLUS_THRESHOLD:
            highlights.append(Highlight(
                highlight_type=HighlightType.TWENTY_PLUS,
                subject_id=p.player_external_id,
                subject_type="player",
                value=float(p.points),
                label=f"{p.points}-point game",
            ))

        if p.blocks >= BLOCK_PARTY_THRESHOLD:
            highlights.append(Highlight(
                highlight_type=HighlightType.BLOCK_PARTY,
                subject_id=p.player_external_id,
                subject_type="player",
                value=float(p.blocks),
                label=f"{p.blocks} blocks",
            ))

        if p.assists >= ASSIST_LEADER_THRESHOLD:
            highlights.append(Highlight(
                highlight_type=HighlightType.ASSIST_LEADER,
                subject_id=p.player_external_id,
                subject_type="player",
                value=float(p.assists),
                label=f"{p.assists} assists",
            ))

        if p.rebounds >= REBOUND_KING_THRESHOLD:
            highlights.append(Highlight(
                highlight_type=HighlightType.REBOUND_KING,
                subject_id=p.player_external_id,
                subject_type="player",
                value=float(p.rebounds),
                label=f"{p.rebounds} rebounds",
            ))

    return highlights


def _detect_team_shooting(home_team: TeamLine, away_team: TeamLine) -> List[Highlight]:
    highlights: List[Highlight] = []

    for team in (home_team, away_team):
        if team.fg_pct >= SHOOTING_DISPLAY_PCT and team.field_goals_attempted >= 40:
            highlights.append(Highlight(
                highlight_type=HighlightType.SHOOTING_DISPLAY,
                subject_id=team.team_external_id,
                subject_type="team",
                value=round(team.fg_pct * 100, 1),
                label=f"{team.fg_pct * 100:.1f}% FG",
            ))

    return highlights
