"""Insight Engine — deterministic story detection.

Pure functions: consume DTOs from the data platform (Match, PlayerStats,
TeamStats) and emit StoryObject instances. No repositories, no IO, no LLM.
Every emitted fact is traceable to a specific data source recorded in
``source_refs`` — the FactValidator enforces this invariant later.

v1 detectors delivered:
  - detect_match_final   (one story per finalized match)
  - detect_player_of_round (best impact score across the round)
  - detect_round_recap    (aggregate summary per round)

Future detectors slot in without touching existing ones.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Sequence

from .bio import LeagueBio
from .names import display_name
from .story import StoryEntities, StoryObject, StoryType


# ---------------------------------------------------------------------------
# Detector inputs — tiny DTOs so the engine stays domain-pure.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MatchFactsInput:
    external_id: str
    season_code: str
    round_number: int
    home_team_external_id: str
    away_team_external_id: str
    home_team_name: Optional[str]
    away_team_name: Optional[str]
    home_score: int
    away_score: int
    scheduled_at: datetime

    @property
    def winner_id(self) -> str:
        return self.home_team_external_id if self.home_score >= self.away_score else self.away_team_external_id

    @property
    def loser_id(self) -> str:
        return self.away_team_external_id if self.home_score >= self.away_score else self.home_team_external_id


@dataclass(frozen=True)
class PlayerLineInput:
    player_external_id: str
    player_name: Optional[str]
    team_external_id: str
    team_name: Optional[str]
    match_external_id: str
    points: int
    rebounds: int
    assists: int
    steals: int = 0
    blocks: int = 0
    turnovers: int = 0
    minutes: float = 0.0
    # Shooting / fouls — OPTIONAL. The domain PlayerStats does not carry these
    # per player yet (only TeamStats does), so they arrive as None today and the
    # shooting detectors self-skip. When the boxscore ingestion plumbs per-player
    # shooting through, these fill in and the detectors light up — no rewrite.
    field_goals_made: Optional[int] = None
    field_goals_attempted: Optional[int] = None
    three_points_made: Optional[int] = None
    three_points_attempted: Optional[int] = None
    free_throws_made: Optional[int] = None
    free_throws_attempted: Optional[int] = None
    fouls: Optional[int] = None
    fouls_received: Optional[int] = None

    @property
    def impact_score(self) -> float:
        return (
            self.points
            + self.rebounds * 1.2
            + self.assists * 1.5
            + self.steals * 2.0
            + self.blocks * 1.5
            - self.turnovers
        )

    @property
    def has_shooting(self) -> bool:
        """True when per-player shooting data is present (attempts recorded)."""
        return self.field_goals_attempted is not None

    @staticmethod
    def _pct(made: Optional[int], att: Optional[int]) -> Optional[float]:
        if made is None or att is None or att == 0:
            return None
        return round(100.0 * made / att, 1)

    @property
    def field_goal_pct(self) -> Optional[float]:
        return self._pct(self.field_goals_made, self.field_goals_attempted)

    @property
    def three_point_pct(self) -> Optional[float]:
        return self._pct(self.three_points_made, self.three_points_attempted)


# ---------------------------------------------------------------------------
# Detectors
# ---------------------------------------------------------------------------


def detect_match_final(match: MatchFactsInput) -> StoryObject:
    facts = {
        "home_team_external_id": match.home_team_external_id,
        "away_team_external_id": match.away_team_external_id,
        "home_team_name": match.home_team_name,
        "away_team_name": match.away_team_name,
        "home_score": match.home_score,
        "away_score": match.away_score,
        "margin": abs(match.home_score - match.away_score),
        "scheduled_at": match.scheduled_at.isoformat(),
    }
    return StoryObject(
        story_type=StoryType.MATCH_FINAL,
        season_code=match.season_code,
        round_number=match.round_number,
        entities=StoryEntities(
            match_external_id=match.external_id,
            home_team_external_id=match.home_team_external_id,
            away_team_external_id=match.away_team_external_id,
        ),
        facts=facts,
        source_refs={
            "match": f"2afeb_score://matches/{match.external_id}",
        },
    )


def detect_player_of_round(
    season_code: str,
    round_number: int,
    player_lines: Sequence[PlayerLineInput],
) -> Optional[StoryObject]:
    """Highest impact score across the round (min 2 players so ties fall out
    of scope). Returns None if no players — no invented content."""
    if not player_lines:
        return None

    best = max(player_lines, key=lambda p: (p.impact_score, p.points))

    facts = player_facts(best)
    return StoryObject(
        story_type=StoryType.PLAYER_OF_ROUND,
        season_code=season_code,
        round_number=round_number,
        entities=StoryEntities(
            player_external_id=best.player_external_id,
            team_external_id=best.team_external_id,
            match_external_id=best.match_external_id,
        ),
        facts=facts,
        source_refs={
            "player_stats": (
                f"2afeb_score://match_player_stats/{best.match_external_id}/"
                f"{best.player_external_id}"
            ),
        },
    )


def _rating_str(v):
    return (f"{v:.1f}").replace(".", ",")


def detect_round_recap(
    season_code: str,
    round_number: int,
    matches: Sequence[MatchFactsInput],
    player_lines: Sequence[PlayerLineInput],
    season_context: "Optional[SeasonContext]" = None,
    bio: "Optional[LeagueBio]" = None,
) -> Optional[StoryObject]:
    """The round in a hierarchy of curated stories: a hero stat, the top
    performance (with its line), and a row of secondary tiles. Each piece is
    drawn from a real detection and omitted when there is no story; fewer than
    three real data points is not a recap. ``bio`` is accepted for signature
    stability (the fun-fact slot was removed)."""
    if not matches:
        return None

    facts: Dict[str, Any] = {"matches_played": len(matches)}
    points = 0

    # --- Top performance: the player of the round, with the line behind it ---
    por = detect_player_of_round(season_code, round_number, player_lines)
    top_pid = por.facts.get("player_external_id") if por else None
    if por:
        f = por.facts
        facts["top"] = {
            "name": f.get("player_name"), "team": f.get("team_name"),
            "team_external_id": f.get("team_external_id"),
            "player_external_id": top_pid,
            "points": f.get("points"), "rebounds": f.get("rebounds"),
            "assists": f.get("assists"), "rating": f.get("rating"),
        }
        points += 1

    biggest = detect_biggest_win(season_code, round_number, matches)

    # --- Hero Stat: the round's biggest scoring number. If that is the top
    # performer too, the hero becomes the biggest win margin so the two never
    # tell the same story. ---
    hero_is_margin = False
    hero = max(player_lines, key=lambda p: p.points) if player_lines else None
    if hero and hero.points > 0 and hero.player_external_id != top_pid:
        facts["hero"] = {
            "value": str(hero.points), "unit": "PTS",
            "note": "Máxima anotación de la jornada",
            "name": display_name(hero.player_name), "team": hero.team_name,
            "team_external_id": hero.team_external_id,
        }
        points += 1
    elif biggest:
        bf = biggest.facts
        win = bf["home_team_name"] if bf["home_score"] >= bf["away_score"] else bf["away_team_name"]
        facts["hero"] = {
            "value": f"+{bf['margin']}", "unit": "",
            "note": "La mayor diferencia de la jornada",
            "name": win, "team": None, "team_external_id": None,
        }
        hero_is_margin = True
        points += 1

    # --- Secondary tiles ---
    tiles: List[Dict[str, Any]] = []
    if biggest and not hero_is_margin:
        bf = biggest.facts
        win = bf["home_team_name"] if bf["home_score"] >= bf["away_score"] else bf["away_team_name"]
        tiles.append({
            "label": "MAYOR DIFERENCIA", "value": f"+{bf['margin']}",
            "sub": f"{win or ''} {bf['home_score']}-{bf['away_score']}".strip(),
        })
    if season_context is not None:
        from .season_insights import detect_streaks
        wins = [st for st in detect_streaks(season_code, round_number, matches, season_context)
                if st.facts.get("streak_kind") == "win"]
        best = max(wins, key=lambda st: st.facts.get("streak_length", 0), default=None)
        if best:
            f = best.facts
            tiles.append({
                "label": "RACHA", "value": str(f["streak_length"]),
                "sub": f.get("team_name") or "",
            })
    # Highest team output of the round — always available from the scores.
    top_team_match = max(matches, key=lambda m: max(m.home_score, m.away_score))
    tp = max(top_team_match.home_score, top_team_match.away_score)
    tt = (top_team_match.home_team_name if top_team_match.home_score >= top_team_match.away_score
          else top_team_match.away_team_name)
    tiles.append({"label": "MÁS ANOTADOR", "value": str(tp), "sub": tt or ""})

    facts["tiles"] = tiles[:3]
    points += len(facts["tiles"])

    if points < 3:
        return None

    return StoryObject(
        story_type=StoryType.ROUND_RECAP,
        season_code=season_code,
        round_number=round_number,
        entities=StoryEntities(),
        facts=facts,
        source_refs={
            "round": f"2afeb_score://seasons/{season_code}/rounds/{round_number}",
        },
    )

BLOWOUT_MARGIN = 20  # a win by 20+ is "the rout of the round" material


def detect_biggest_win(
    season_code: str,
    round_number: int,
    matches: Sequence[MatchFactsInput],
) -> Optional[StoryObject]:
    """The largest-margin win of the round, when it qualifies as a blowout.

    Framed as its own editorial piece (distinct from the plain MATCH_FINAL of
    the same game). Returns None when no match reaches the blowout margin — no
    manufactured drama."""
    if not matches:
        return None
    match = max(matches, key=lambda m: abs(m.home_score - m.away_score))
    margin = abs(match.home_score - match.away_score)
    if margin < BLOWOUT_MARGIN:
        return None

    facts = {
        "home_team_external_id": match.home_team_external_id,
        "away_team_external_id": match.away_team_external_id,
        "home_team_name": match.home_team_name,
        "away_team_name": match.away_team_name,
        "home_score": match.home_score,
        "away_score": match.away_score,
        "margin": margin,
        "scheduled_at": match.scheduled_at.isoformat(),
    }
    return StoryObject(
        story_type=StoryType.BIGGEST_WIN,
        season_code=season_code,
        round_number=round_number,
        entities=StoryEntities(
            match_external_id=match.external_id,
            home_team_external_id=match.home_team_external_id,
            away_team_external_id=match.away_team_external_id,
        ),
        facts=facts,
        source_refs={"match": f"2afeb_score://matches/{match.external_id}"},
    )


def _count_double_digits(p: PlayerLineInput) -> int:
    return sum(1 for v in (p.points, p.rebounds, p.assists, p.steals, p.blocks) if v >= 10)


def detect_notable_performances(
    season_code: str,
    round_number: int,
    player_lines: Sequence[PlayerLineInput],
) -> List[StoryObject]:
    """Double-doubles and triple-doubles of the round (one story per player).

    Deterministic: a double-double is >=2 categories at 10+, a triple-double
    >=3. Both are demonstrable from the boxscore line alone."""
    stories: List[StoryObject] = []
    for p in player_lines:
        doubles = _count_double_digits(p)
        if doubles < 2:
            continue
        story_type = StoryType.TRIPLE_DOUBLE if doubles >= 3 else StoryType.DOUBLE_DOUBLE
        facts = player_facts(p)
        facts["double_digit_count"] = doubles
        stories.append(StoryObject(
            story_type=story_type,
            season_code=season_code,
            round_number=round_number,
            entities=StoryEntities(
                player_external_id=p.player_external_id,
                team_external_id=p.team_external_id,
                match_external_id=p.match_external_id,
            ),
            facts=facts,
            source_refs={
                "player_stats": (
                    f"2afeb_score://match_player_stats/{p.match_external_id}/"
                    f"{p.player_external_id}"
                ),
            },
        ))
    return stories


def detect_best_five(
    season_code: str,
    round_number: int,
    player_lines: Sequence[PlayerLineInput],
) -> Optional[StoryObject]:
    """The round's five best players by FEB Rating (a ranking, not a lineup).
    Needs five players who can actually be rated (enough minutes + shooting), so
    the note is never a stand-in — a round short of five rated players yields no
    quinteto rather than one padded with unrated names."""
    rated = [(p, _rating_of(p)) for p in player_lines]
    rated = [(p, r) for p, r in rated if r is not None]
    if len(rated) < 5:
        return None
    rated.sort(key=lambda pr: (-pr[1], -pr[0].points, pr[0].player_external_id))
    top = rated[:5]
    lineup = [
        {
            "rank": i,
            "player_external_id": p.player_external_id,
            "player_name": display_name(p.player_name),
            "team_external_id": p.team_external_id,
            "team_name": p.team_name,
            "points": p.points,
            "rebounds": p.rebounds,
            "assists": p.assists,
            "rating": r,
            "match_external_id": p.match_external_id,
        }
        for i, (p, r) in enumerate(top, start=1)
    ]
    from .rating import FEB_RATING_VERSION
    return StoryObject(
        story_type=StoryType.BEST_FIVE,
        season_code=season_code,
        round_number=round_number,
        entities=StoryEntities(),
        facts={"lineup": lineup, "count": 5, "rating_version": FEB_RATING_VERSION},
        source_refs={
            "player_stats": (
                "2afeb_score://match_player_stats/" + top[0][0].match_external_id
            ),
        },
    )


def detect_best_five_ideal(
    season_code: str,
    round_number: int,
    player_lines: Sequence[PlayerLineInput],
    bio: Optional["LeagueBio"] = None,
) -> Optional[StoryObject]:
    """The round's ideal FIVE by position: the best-rated player at each of the
    five court positions (base, escolta, alero, ala-pívot, pívot). A true
    lineup, placed on court — so it needs a rated player at EVERY position, and
    a round short of one position yields no card rather than a hole in the five.
    Self-skips without roster positions."""
    from .bio import POSITIONS

    if not bio:
        return None
    best: Dict[str, tuple] = {}
    for p in player_lines:
        pos = bio.position(p.player_external_id)
        if pos is None:
            continue
        rating = _rating_of(p)
        if rating is None:
            continue
        cur = best.get(pos)
        if cur is None or rating > cur[1] or (rating == cur[1] and p.points > cur[0].points):
            best[pos] = (p, rating)
    if any(pos not in best for pos in POSITIONS):
        return None
    # Ordered to match the court spots (pívot, ala-pívot, alero, base, escolta).
    lineup = []
    for pos in POSITIONS:
        p, rating = best[pos]
        lineup.append({
            "position": pos,
            "player_external_id": p.player_external_id,
            "player_name": display_name(p.player_name),
            "team_external_id": p.team_external_id,
            "team_name": p.team_name,
            "points": p.points,
            "rebounds": p.rebounds,
            "assists": p.assists,
            "rating": rating,
            "match_external_id": p.match_external_id,
        })
    from .rating import FEB_RATING_VERSION
    return StoryObject(
        story_type=StoryType.BEST_FIVE_IDEAL,
        season_code=season_code,
        round_number=round_number,
        entities=StoryEntities(),
        facts={"lineup": lineup, "count": 5, "rating_version": FEB_RATING_VERSION},
        source_refs={
            "player_stats": (
                "2afeb_score://match_player_stats/" + lineup[0]["match_external_id"]
            ),
        },
    )


def detect_stat_leaderboard(
    season_code: str,
    round_number: int,
    player_lines: Sequence[PlayerLineInput],
    top_n: int = 5,
) -> Optional[StoryObject]:
    """The round's top scorers as a ranking (name, team, points, FEB Rating).
    Needs at least 3 players so a ranking is meaningful."""
    from .rating import FEB_RATING_VERSION, feb_rating

    if len(player_lines) < 3:
        return None
    ordered = sorted(player_lines, key=lambda p: (-p.points, p.player_external_id))[:top_n]
    leaders = [
        {
            "rank": i,
            "player_external_id": p.player_external_id,
            "player_name": display_name(p.player_name),
            "team_external_id": p.team_external_id,
            "team_name": p.team_name,
            "points": p.points,
            "rebounds": p.rebounds,
            "assists": p.assists,
            "rating": _rating_of(p),
        }
        for i, p in enumerate(ordered, start=1)
    ]
    return StoryObject(
        story_type=StoryType.STAT_LEADERBOARD,
        season_code=season_code,
        round_number=round_number,
        entities=StoryEntities(),
        facts={
            "leaders": leaders,
            "count": len(leaders),
            "rating_version": FEB_RATING_VERSION,
        },
        source_refs={
            "player_stats": (
                f"2afeb_score://seasons/{season_code}/rounds/{round_number}/player_stats"
            ),
        },
    )


# ---------------------------------------------------------------------------
# Curious & shooting player angles (single-player, framed by a chosen hero stat)
# ---------------------------------------------------------------------------
# These reuse the player card but pick their OWN hero stat (assists, minutes,
# threes…) via display hints in the facts, so the same template tells a
# different story. Shooting detectors self-skip when per-player shooting data is
# absent (``has_shooting``), so they stay dormant until the ingestion carries it.

MINUTES_HEAVY = 35.0        # a 35'+ night on a 40' game = a real workhorse
PLAYMAKER_MIN_ASSISTS = 8   # 8+ assists = a genuine facilitator night
SHARP_MIN_THREES = 5        # 5+ made threes = a shooting show
PERFECT_MIN_FG_ATT = 5      # 5+ attempts, no misses = a perfect night
# Measured over 2,607 real player-lines (2024-25, rounds 18-26): robos+tapones
# has a median of 1 and a 95th percentile of 3. At 5 the detector sees ~2.3
# candidates a round (the top 0.8% of lines) and fires in 8 rounds out of 9 —
# rare enough to mean something, common enough to be a lane. At 4 it would be
# 10 a round, i.e. an ordinary night dressed up as a story.
DEFENSIVE_MIN_ACTIONS = 5   # steals + blocks
# Measured on 174 real lines from players who are their country's only
# representative (2024-25, rounds 18-26): median 8 points, p90 19. At 15 the
# card lands on a genuinely above-average night and fired in 9 rounds out of 9.
LONE_FLAG_MIN_POINTS = 15
# Age lanes. Measured on 443 real players (2024-25): median age 24, p10 18, and
# 85 players are 20 or under. Requiring a real game (>=12 pts) AND age <=20 for
# the prospect / >=34 for the veteran, both lanes fired in 9 of 9 sampled rounds
# with genuine subjects (a 16-year-old for 21, a 41-year-old for 13). The age is
# the hook, so it is the hero number; points sit beside it.
YOUNG_GUN_MAX_AGE = 20
VETERAN_MIN_AGE = 34
AGE_CURIO_MIN_POINTS = 12


def _rating_of(p: PlayerLineInput) -> Optional[float]:
    """The FEB Rating for a line, or None when it cannot be rated on the same
    basis as the rest (too few minutes, or no shooting data). ONE mapping from
    a player line to the mark, so no call site can rate on a different input
    set and produce a note that is not comparable."""
    from .rating import feb_rating

    return feb_rating(
        p.points, p.rebounds, p.assists, p.steals, p.blocks, p.turnovers,
        minutes=p.minutes,
        field_goals_made=p.field_goals_made,
        field_goals_attempted=p.field_goals_attempted,
        free_throws_made=p.free_throws_made or 0,
        free_throws_attempted=p.free_throws_attempted or 0,
        three_points_made=p.three_points_made or 0,
        fouls=p.fouls or 0,
        fouls_received=p.fouls_received or 0,
    )


def player_facts(p: PlayerLineInput) -> Dict[str, Any]:
    """THE canonical fact set for a player-card story.

    Includes the FEB Rating: it is a derived, versioned, deterministic fact (like
    impact_score), so every player card can show the signature mark and the
    validator can check it. Building every player story through here keeps the
    rating from silently missing on some card types.
    """
    from .rating import FEB_RATING_VERSION, feb_rating

    return {
        "player_external_id": p.player_external_id,
        "player_name": display_name(p.player_name),
        "team_external_id": p.team_external_id,
        "team_name": p.team_name,
        "points": p.points,
        "rebounds": p.rebounds,
        "assists": p.assists,
        "steals": p.steals,
        "blocks": p.blocks,
        "turnovers": p.turnovers,
        "minutes": p.minutes,
        "minutes_played": int(round(p.minutes)),
        "impact_score": round(p.impact_score, 1),
        "rating": _rating_of(p),
        "rating_version": FEB_RATING_VERSION,
        "match_external_id": p.match_external_id,
    }


def _player_story(story_type: StoryType, season_code: str, round_number: int,
                  p: PlayerLineInput, extra: Dict[str, Any]) -> StoryObject:
    facts = player_facts(p)
    facts.update(extra)
    return StoryObject(
        story_type=story_type,
        season_code=season_code,
        round_number=round_number,
        entities=StoryEntities(
            player_external_id=p.player_external_id,
            team_external_id=p.team_external_id,
            match_external_id=p.match_external_id,
        ),
        facts=facts,
        source_refs={
            "player_stats": (
                f"2afeb_score://match_player_stats/{p.match_external_id}/"
                f"{p.player_external_id}"
            ),
        },
    )


def detect_iron_man(
    season_code: str, round_number: int, player_lines: Sequence[PlayerLineInput],
) -> Optional[StoryObject]:
    """The workhorse of the round — most minutes, when it clears a heavy load.
    Skips silently when minutes aren't recorded (all 0)."""
    heavy = [p for p in player_lines if p.minutes >= MINUTES_HEAVY]
    if not heavy:
        return None
    p = max(heavy, key=lambda x: (x.minutes, x.points))
    return _player_story(StoryType.IRON_MAN, season_code, round_number, p, {
        "hero_value": int(round(p.minutes)), "hero_label": "MIN",
        "secondary": [[p.points, "PTS"], [p.rebounds, "REB"]],
        "badge_label": "MARATÓN", "section_label": "El más trabajador",
    })


def detect_playmaker(
    season_code: str, round_number: int, player_lines: Sequence[PlayerLineInput],
) -> Optional[StoryObject]:
    """The round's chief facilitator — the assist leader, when assists reach a
    real playmaking night (frames a card by assists, not points)."""
    eligible = [p for p in player_lines if p.assists >= PLAYMAKER_MIN_ASSISTS]
    if not eligible:
        return None
    p = max(eligible, key=lambda x: (x.assists, x.points))
    return _player_story(StoryType.PLAYMAKER, season_code, round_number, p, {
        "hero_value": p.assists, "hero_label": "AST",
        "secondary": [[p.points, "PTS"], [p.rebounds, "REB"]],
        "badge_label": "DIRECTOR", "section_label": "El director de juego",
    })


def detect_defensive_anchor(
    season_code: str, round_number: int, player_lines: Sequence[PlayerLineInput],
) -> Optional[StoryObject]:
    """The best defensive night of the round — steals plus blocks.

    Defence barely registers in a boxscore, so without a card of its own it
    never gets told: five blocks in a five-point night loses every ranking to
    the scorers. The hero number is the SUM, with both parts shown beside it so
    a reader can check the arithmetic rather than take it on trust.
    """
    eligible = [
        p for p in player_lines
        if (p.steals + p.blocks) >= DEFENSIVE_MIN_ACTIONS
    ]
    if not eligible:
        return None
    p = max(eligible, key=lambda x: (x.steals + x.blocks, x.points))
    actions = p.steals + p.blocks
    return _player_story(StoryType.DEFENSIVE_ANCHOR, season_code, round_number, p, {
        "defensive_actions": actions,
        "hero_value": actions, "hero_label": "ROB+TAP",
        "secondary": [[p.steals, "ROB"], [p.blocks, "TAP"]],
        "badge_label": "DEFENSA", "section_label": "El muro de la jornada",
    })


def detect_lone_flag(
    season_code: str, round_number: int, player_lines: Sequence[PlayerLineInput],
    bio: Optional["LeagueBio"] = None,
) -> Optional[StoryObject]:
    """The season's ONLY player from some country, having a real game.

    Every other detector ranks a boxscore column, which is the one thing a
    scoreboard already does. This one needs the roster to say anything at all —
    and it turns out Segunda FEB fields 53 nationalities, 27 of them with a
    single player.

    Self-skips without bio data, so the lane stays dark until the roster is
    wired rather than guessing at a nationality.
    """
    if not bio:
        return None
    eligible = [
        p for p in player_lines
        if p.points >= LONE_FLAG_MIN_POINTS
        and bio.is_sole_representative(p.player_external_id)
    ]
    if not eligible:
        return None
    p = max(eligible, key=lambda x: (x.impact_score, x.points))
    country = bio.nationality(p.player_external_id)
    return _player_story(StoryType.LONE_FLAG, season_code, round_number, p, {
        "nationality": country,
        "countrymen_in_season": bio.countrymen(p.player_external_id),
        "hero_value": p.points, "hero_label": "PTS",
        "secondary": [[p.rebounds, "REB"], [p.assists, "AST"]],
        "badge_label": "ÚNICO",
        "section_label": f"El único de {country}",
    })


def _round_reference_date(matches: "Sequence[MatchFactsInput]"):
    """A single date to age players against: the latest match of the round.
    None when no match carries a date (the age lanes then self-skip)."""
    dates = [m.scheduled_at for m in matches if getattr(m, "scheduled_at", None)]
    return max(dates).date() if dates else None


def _age_story(story_type, season_code, round_number, p, age, extra):
    facts = {"age": age, "hero_value": age, "hero_label": "AÑOS",
             "secondary": [[p.points, "PTS"], [p.rebounds, "REB"]]}
    facts.update(extra)
    return _player_story(story_type, season_code, round_number, p, facts)


def detect_young_gun(
    season_code: str, round_number: int, player_lines: Sequence[PlayerLineInput],
    bio: Optional["LeagueBio"] = None,
    matches: "Sequence[MatchFactsInput]" = (),
) -> Optional[StoryObject]:
    """The youngest player of the round to actually produce — a genuine prospect
    (<= YOUNG_GUN_MAX_AGE) with a real scoring line. Age is the hook, computed
    against the round's date. Self-skips without birth dates.
    """
    ref = _round_reference_date(matches)
    if not bio or ref is None:
        return None
    graded = []
    for p in player_lines:
        if p.points < AGE_CURIO_MIN_POINTS:
            continue
        age = bio.age_on(p.player_external_id, ref)
        if age is not None and age <= YOUNG_GUN_MAX_AGE:
            graded.append((age, p))
    if not graded:
        return None
    # Youngest first; a strong game breaks ties toward the better story.
    age, p = min(graded, key=lambda ap: (ap[0], -ap[1].points))
    return _age_story(StoryType.YOUNG_GUN, season_code, round_number, p, age, {
        "badge_label": "PROMESA", "section_label": "La joven promesa",
    })


def detect_veteran(
    season_code: str, round_number: int, player_lines: Sequence[PlayerLineInput],
    bio: Optional["LeagueBio"] = None,
    matches: "Sequence[MatchFactsInput]" = (),
) -> Optional[StoryObject]:
    """The oldest player of the round still delivering — a real veteran
    (>= VETERAN_MIN_AGE) with a real scoring line."""
    ref = _round_reference_date(matches)
    if not bio or ref is None:
        return None
    graded = []
    for p in player_lines:
        if p.points < AGE_CURIO_MIN_POINTS:
            continue
        age = bio.age_on(p.player_external_id, ref)
        if age is not None and age >= VETERAN_MIN_AGE:
            graded.append((age, p))
    if not graded:
        return None
    age, p = max(graded, key=lambda ap: (ap[0], ap[1].points))
    return _age_story(StoryType.VETERAN, season_code, round_number, p, age, {
        "badge_label": "VETERANO", "section_label": "El veterano",
    })


def detect_sharpshooter(
    season_code: str, round_number: int, player_lines: Sequence[PlayerLineInput],
) -> Optional[StoryObject]:
    """The best 3-point game of the round (most made, then best %). Needs
    per-player shooting data — dormant until the ingestion carries it."""
    eligible = [
        p for p in player_lines
        if p.has_shooting and (p.three_points_made or 0) >= SHARP_MIN_THREES
    ]
    if not eligible:
        return None
    p = max(eligible, key=lambda x: (x.three_points_made, x.three_point_pct or 0.0, x.points))
    return _player_story(StoryType.SHARPSHOOTER, season_code, round_number, p, {
        "three_points_made": p.three_points_made,
        "three_points_attempted": p.three_points_attempted,
        "three_point_pct": p.three_point_pct,
        "hero_value": p.three_points_made, "hero_label": "TRIPLES",
        "secondary": [[p.points, "PTS"], [p.three_points_attempted, "INT"]],
        "badge_label": "SNIPER", "section_label": "El tirador de la jornada",
    })


def detect_perfect_night(
    season_code: str, round_number: int, player_lines: Sequence[PlayerLineInput],
) -> Optional[StoryObject]:
    """A player who didn't miss from the field, with real volume. Needs
    per-player shooting data — dormant until the ingestion carries it."""
    eligible = [
        p for p in player_lines
        if p.has_shooting and (p.field_goals_attempted or 0) >= PERFECT_MIN_FG_ATT
        and p.field_goals_made == p.field_goals_attempted
    ]
    if not eligible:
        return None
    p = max(eligible, key=lambda x: (x.field_goals_attempted, x.points))
    return _player_story(StoryType.PERFECT_NIGHT, season_code, round_number, p, {
        "field_goals_made": p.field_goals_made,
        "field_goals_attempted": p.field_goals_attempted,
        "field_goal_pct": p.field_goal_pct,
        "hero_value": p.points, "hero_label": "PTS",
        "secondary": [[p.field_goals_made, "TC"], [p.rebounds, "REB"]],
        "badge_label": "SIN FALLO", "section_label": "Noche perfecta",
    })


DUO_MIN_COMBINED = 35  # two teammates must combine for a real haul to be a story


def detect_best_duo(
    season_code: str, round_number: int, player_lines: Sequence[PlayerLineInput],
) -> Optional[StoryObject]:
    """The round's best pair of TEAMMATES: the two highest scorers on the same
    team in the same game, by combined points. Needs two players from one
    team-game; skips below the combined threshold (no manufactured duo)."""
    from collections import defaultdict

    from .rating import FEB_RATING_VERSION, feb_rating

    groups: Dict[tuple, List[PlayerLineInput]] = defaultdict(list)
    for p in player_lines:
        groups[(p.match_external_id, p.team_external_id)].append(p)

    best: Optional[tuple] = None  # (combined, p1, p2)
    for members in groups.values():
        if len(members) < 2:
            continue
        p1, p2 = sorted(members, key=lambda x: (-x.points, x.player_external_id))[:2]
        combined = p1.points + p2.points
        if best is None or combined > best[0]:
            best = (combined, p1, p2)
    if best is None or best[0] < DUO_MIN_COMBINED:
        return None
    combined, p1, p2 = best

    def _rt(p: PlayerLineInput) -> float:
        return _rating_of(p)

    facts = {
        "team_external_id": p1.team_external_id,
        "team_name": p1.team_name,
        "match_external_id": p1.match_external_id,
        "p1_external_id": p1.player_external_id, "p1_name": display_name(p1.player_name),
        "p1_points": p1.points, "p1_rating": _rt(p1),
        "p2_external_id": p2.player_external_id, "p2_name": display_name(p2.player_name),
        "p2_points": p2.points, "p2_rating": _rt(p2),
        "combined_points": combined,
        "rating_version": FEB_RATING_VERSION,
    }
    return StoryObject(
        story_type=StoryType.BEST_DUO,
        season_code=season_code,
        round_number=round_number,
        entities=StoryEntities(
            team_external_id=p1.team_external_id, match_external_id=p1.match_external_id,
        ),
        facts=facts,
        source_refs={
            "player_stats": (
                f"2afeb_score://match_player_stats/{p1.match_external_id}"
            ),
        },
    )


# ---------------------------------------------------------------------------
# Round-level convenience entry point
# ---------------------------------------------------------------------------


def detect_all_for_round(
    season_code: str,
    round_number: int,
    matches: Sequence[MatchFactsInput],
    player_lines: Sequence[PlayerLineInput],
) -> List[StoryObject]:
    """Run every ROUND-scope detector and return the raw stories. Delegates to
    the detector registry (the single source of truth); kept as a convenience
    entry point. The Planner scores/selects; this only emits."""
    from .registry import DetectionContext, Scope, run_detectors  # lazy: avoid import cycle

    ctx = DetectionContext(
        season_code=season_code, round_number=round_number,
        matches=tuple(matches), player_lines=tuple(player_lines),
    )
    return run_detectors(ctx, {Scope.ROUND})
