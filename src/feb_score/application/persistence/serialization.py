"""JSON-safe serialization for domain aggregates.

Enables the round-trip required by persistent storage:

    object -> serialize -> dict (JSON-safe) -> persist
    dict (load) -> deserialize -> object equivalente

All datetimes become ISO-8601 strings, all IDs/enums become strings and all
nested values become plain dicts/lists, so the output is directly storable in
SQLite JSON columns or an event table. The reconstructed aggregate re-applies
domain invariants via its dataclass ``__post_init__``.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Callable, Dict, List, Optional, Tuple

from ...domain.competition.model import Competition, RoundDefinition, Season
from ...domain.correction.model import CorrectionProposal
from ...domain.leaderboard.model import Leaderboard, LeaderboardEntry
from ...domain.match.model import Match
from ...domain.player.model import Player, PlayerRegistration
from ...domain.publication.model import Publication
from ...domain.ratings.model import PlayerRating
from ...domain.standings.model import StandingEntry, StandingSnapshot
from ...domain.statistics.model import PlayerStats, TeamStats
from ...domain.team.model import Team, TeamPlayerRegistration
from ...domain.value_objects import (
    Actor,
    CompetitionId,
    CorrectionProposalId,
    ExternalId,
    LeaderboardId,
    MatchId,
    MatchStatus,
    PlayerId,
    PublicationId,
    RatingValue,
    RatingVersion,
    SeasonCode,
    SnapshotId,
    ScoreSummary,
    PeriodScore,
    TeamId,
)


# ---------------------------------------------------------------------------
# scalar helpers
# ---------------------------------------------------------------------------

def _iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.isoformat() if dt is not None else None


def _parse_dt(value: Optional[str]) -> Optional[datetime]:
    return datetime.fromisoformat(value) if value is not None else None


def _iso_date(d: Optional[date]) -> Optional[str]:
    return d.isoformat() if d is not None else None


def _parse_date(value: Optional[str]) -> Optional[date]:
    return date.fromisoformat(value) if value is not None else None


def _actor_to_dict(actor: Optional[Actor]) -> Optional[Dict[str, str]]:
    return {"id": actor.id, "role": actor.role} if actor is not None else None


def _actor_from_dict(data: Optional[Dict[str, str]]) -> Optional[Actor]:
    return Actor(id=data["id"], role=data["role"]) if data is not None else None


# ---------------------------------------------------------------------------
# Match
# ---------------------------------------------------------------------------

def _score_summary_to_dict(score: Optional[ScoreSummary]) -> Optional[Dict[str, Any]]:
    if score is None:
        return None
    return {
        "home_score": score.home_score,
        "away_score": score.away_score,
        "periods": [
            {"period": p.period, "home": p.home, "away": p.away} for p in score.periods
        ],
    }


def _score_summary_from_dict(data: Optional[Dict[str, Any]]) -> Optional[ScoreSummary]:
    if data is None:
        return None
    return ScoreSummary(
        home_score=data["home_score"],
        away_score=data["away_score"],
        periods=tuple(
            PeriodScore(period=p["period"], home=p["home"], away=p["away"])
            for p in data.get("periods", [])
        ),
    )


def _team_stats_to_dict(stats: Optional[TeamStats]) -> Optional[Dict[str, Any]]:
    if stats is None:
        return None
    return stats.to_dict()


def _team_stats_from_dict(data: Optional[Dict[str, Any]]) -> Optional[TeamStats]:
    if data is None:
        return None
    return TeamStats(**data)


def _player_stats_to_dict(stats: PlayerStats) -> Dict[str, Any]:
    return stats.to_dict()


def _player_stats_from_dict(data: Dict[str, Any]) -> PlayerStats:
    # played_at is serialized as an ISO string by to_dict; parse it back to a
    # datetime so a load→save round-trip (e.g. finalize) doesn't call
    # .isoformat() on a str.
    if isinstance(data.get("played_at"), str):
        data = {**data, "played_at": _parse_dt(data["played_at"])}
    return PlayerStats(**data)


def match_to_dict(match: Match) -> Dict[str, Any]:
    return {
        "external_id": str(match.external_id),
        "match_id": str(match.match_id),
        "competition_id": str(match.competition_id),
        "season_code": str(match.season_code),
        "round_number": match.round_number,
        "home_team_id": str(match.home_team_id),
        "away_team_id": str(match.away_team_id),
        "scheduled_at": _iso(match.scheduled_at),
        "status": str(match.status),
        "source": match.source,
        "venue": match.venue,
        "raw": match.raw,
        "score_summary": _score_summary_to_dict(match.score_summary),
        "home_team_stats": _team_stats_to_dict(match.home_team_stats),
        "away_team_stats": _team_stats_to_dict(match.away_team_stats),
        "player_stats": [_player_stats_to_dict(ps) for ps in match.player_stats],
        "version": match.version,
        "correction_history": match.correction_history,
    }


def match_from_dict(data: Dict[str, Any]) -> Match:
    return Match(
        external_id=ExternalId(data["external_id"]),
        match_id=MatchId(data["match_id"]),
        competition_id=CompetitionId(data["competition_id"]),
        season_code=SeasonCode(data["season_code"]),
        round_number=data["round_number"],
        home_team_id=ExternalId(data["home_team_id"]),
        away_team_id=ExternalId(data["away_team_id"]),
        scheduled_at=_parse_dt(data["scheduled_at"]),
        status=MatchStatus(data["status"]),
        source=data["source"],
        venue=data.get("venue"),
        raw=data.get("raw"),
        score_summary=_score_summary_from_dict(data.get("score_summary")),
        home_team_stats=_team_stats_from_dict(data.get("home_team_stats")),
        away_team_stats=_team_stats_from_dict(data.get("away_team_stats")),
        player_stats=tuple(_player_stats_from_dict(ps) for ps in data.get("player_stats", [])),
        version=data["version"],
        correction_history=list(data.get("correction_history", [])),
    )


# ---------------------------------------------------------------------------
# Player / PlayerRegistration / Team / TeamPlayerRegistration
# ---------------------------------------------------------------------------

def _registration_to_dict(reg: PlayerRegistration) -> Dict[str, Any]:
    return {
        "team_external_id": reg.team_external_id,
        "season_code": str(reg.season_code),
        "registration_id": reg.registration_id,
        "dorsal": reg.dorsal,
        "registered_at": _iso_date(reg.registered_at),
        "registered_to": _iso_date(reg.registered_to),
        "role": reg.role,
    }


def _registration_from_dict(data: Dict[str, Any]) -> PlayerRegistration:
    return PlayerRegistration(
        team_external_id=data["team_external_id"],
        season_code=SeasonCode(data["season_code"]),
        registration_id=data["registration_id"],
        dorsal=data.get("dorsal"),
        registered_at=_parse_date(data.get("registered_at")),
        registered_to=_parse_date(data.get("registered_to")),
        role=data.get("role"),
    )


def player_to_dict(player: Player) -> Dict[str, Any]:
    return {
        "external_id": str(player.external_id),
        "player_id": str(player.player_id),
        "name": player.name,
        "birth_date": _iso_date(player.birth_date),
        "nationality": player.nationality,
        "position": player.position,
        "height_cm": player.height_cm,
        "birth_place": player.birth_place,
        "registrations": [_registration_to_dict(reg) for reg in player.registrations],
    }


def player_from_dict(data: Dict[str, Any]) -> Player:
    return Player(
        external_id=ExternalId(data["external_id"]),
        player_id=PlayerId(data["player_id"]),
        name=data["name"],
        birth_date=_parse_date(data.get("birth_date")),
        nationality=data.get("nationality"),
        position=data.get("position"),
        height_cm=data.get("height_cm"),
        birth_place=data.get("birth_place"),
        registrations=[_registration_from_dict(reg) for reg in data.get("registrations", [])],
    )


def _team_registration_to_dict(reg: TeamPlayerRegistration) -> Dict[str, Any]:
    return {
        "player_external_id": reg.player_external_id,
        "season_code": str(reg.season_code),
        "registration_id": reg.registration_id,
        "dorsal": reg.dorsal,
    }


def _team_registration_from_dict(data: Dict[str, Any]) -> TeamPlayerRegistration:
    return TeamPlayerRegistration(
        player_external_id=data["player_external_id"],
        season_code=SeasonCode(data["season_code"]),
        registration_id=data["registration_id"],
        dorsal=data.get("dorsal"),
    )


def team_to_dict(team: Team) -> Dict[str, Any]:
    return {
        "external_id": str(team.external_id),
        "team_id": str(team.team_id),
        "name": team.name,
        "registrations": [_team_registration_to_dict(reg) for reg in team.registrations],
    }


def team_from_dict(data: Dict[str, Any]) -> Team:
    return Team(
        external_id=ExternalId(data["external_id"]),
        team_id=TeamId(data["team_id"]),
        name=data["name"],
        registrations=[
            _team_registration_from_dict(reg) for reg in data.get("registrations", [])
        ],
    )


# ---------------------------------------------------------------------------
# Competition / Season / RoundDefinition
# ---------------------------------------------------------------------------

def _round_to_dict(round_definition: RoundDefinition) -> Dict[str, Any]:
    return {"number": round_definition.number, "label": round_definition.label}


def _round_from_dict(data: Dict[str, Any]) -> RoundDefinition:
    return RoundDefinition(number=data["number"], label=data["label"])


def _season_to_dict(season: Season) -> Dict[str, Any]:
    return {
        "season_code": str(season.season_code),
        "rules_version": season.rules_version,
        "rounds": [_round_to_dict(r) for r in season.rounds],
    }


def _season_from_dict(data: Dict[str, Any]) -> Season:
    season = Season(season_code=SeasonCode(data["season_code"]), rules_version=data["rules_version"])
    for round_data in data.get("rounds", []):
        season.add_round(_round_from_dict(round_data))
    return season


def competition_to_dict(competition: Competition) -> Dict[str, Any]:
    return {
        "external_id": str(competition.external_id),
        "competition_id": str(competition.competition_id),
        "name": competition.name,
        "seasons": {code: _season_to_dict(season) for code, season in competition.seasons.items()},
    }


def competition_from_dict(data: Dict[str, Any]) -> Competition:
    return Competition(
        external_id=ExternalId(data["external_id"]),
        competition_id=CompetitionId(data["competition_id"]),
        name=data["name"],
        seasons={code: _season_from_dict(s) for code, s in data.get("seasons", {}).items()},
    )


# ---------------------------------------------------------------------------
# CorrectionProposal
# ---------------------------------------------------------------------------

def correction_to_dict(proposal: CorrectionProposal) -> Dict[str, Any]:
    return {
        "proposal_id": str(proposal.proposal_id),
        "match_external_id": str(proposal.match_external_id),
        "proposed_by": _actor_to_dict(proposal.proposed_by),
        "proposed_at": _iso(proposal.proposed_at),
        "reason": proposal.reason,
        "changes": proposal.changes,
        "status": proposal.status,
        "approved_by": _actor_to_dict(proposal.approved_by),
        "approved_at": _iso(proposal.approved_at),
        "previous_version": proposal.previous_version,
        "new_version": proposal.new_version,
        "rejected_by": _actor_to_dict(proposal.rejected_by),
        "rejected_at": _iso(proposal.rejected_at),
        "rejection_reason": proposal.rejection_reason,
        "comment": proposal.comment,
    }


def correction_from_dict(data: Dict[str, Any]) -> CorrectionProposal:
    return CorrectionProposal(
        proposal_id=CorrectionProposalId(data["proposal_id"]),
        match_external_id=ExternalId(data["match_external_id"]),
        proposed_by=_actor_from_dict(data["proposed_by"]),
        proposed_at=_parse_dt(data["proposed_at"]),
        reason=data["reason"],
        changes=data["changes"],
        status=data.get("status", "PROPOSED"),
        approved_by=_actor_from_dict(data.get("approved_by")),
        approved_at=_parse_dt(data.get("approved_at")),
        previous_version=data.get("previous_version"),
        new_version=data.get("new_version"),
        rejected_by=_actor_from_dict(data.get("rejected_by")),
        rejected_at=_parse_dt(data.get("rejected_at")),
        rejection_reason=data.get("rejection_reason"),
        comment=data.get("comment"),
    )


# ---------------------------------------------------------------------------
# StandingSnapshot
# ---------------------------------------------------------------------------

def _standing_entry_to_dict(entry: StandingEntry) -> Dict[str, Any]:
    return {
        "team_external_id": entry.team_external_id,
        "played": entry.played,
        "wins": entry.wins,
        "losses": entry.losses,
        "points_for": entry.points_for,
        "points_against": entry.points_against,
        "points_difference": entry.points_difference,
        "points": entry.points,
    }


def _standing_entry_from_dict(data: Dict[str, Any]) -> StandingEntry:
    return StandingEntry(**data)


def standing_to_dict(snapshot: StandingSnapshot) -> Dict[str, Any]:
    return {
        "snapshot_id": str(snapshot.snapshot_id),
        "competition_id": str(snapshot.competition_id),
        "season_code": str(snapshot.season_code),
        "generated_at": _iso(snapshot.generated_at),
        "rounds_included": snapshot.rounds_included,
        "matches_count": snapshot.matches_count,
        "rules_version": snapshot.rules_version,
        "description": snapshot.description,
        "entries": [_standing_entry_to_dict(entry) for entry in snapshot.entries],
    }


def standing_from_dict(data: Dict[str, Any]) -> StandingSnapshot:
    return StandingSnapshot(
        snapshot_id=SnapshotId(data["snapshot_id"]),
        competition_id=CompetitionId(data["competition_id"]),
        season_code=SeasonCode(data["season_code"]),
        generated_at=_parse_dt(data["generated_at"]),
        rounds_included=data["rounds_included"],
        matches_count=data["matches_count"],
        rules_version=data["rules_version"],
        description=data.get("description"),
        entries=[_standing_entry_from_dict(e) for e in data.get("entries", [])],
    )


# ---------------------------------------------------------------------------
# Leaderboard
# ---------------------------------------------------------------------------

def _leaderboard_entry_to_dict(entry: LeaderboardEntry) -> Dict[str, Any]:
    return {
        "player_external_id": entry.player_external_id,
        "team_external_id": entry.team_external_id,
        "games": entry.games,
        "value": entry.value,
    }


def _leaderboard_entry_from_dict(data: Dict[str, Any]) -> LeaderboardEntry:
    return LeaderboardEntry(**data)


def leaderboard_to_dict(board: Leaderboard) -> Dict[str, Any]:
    return {
        "leaderboard_id": str(board.leaderboard_id),
        "season_code": str(board.season_code),
        "category": board.category,
        "generated_at": _iso(board.generated_at),
        "min_games": board.min_games,
        "entries": [_leaderboard_entry_to_dict(entry) for entry in board.entries],
    }


def leaderboard_from_dict(data: Dict[str, Any]) -> Leaderboard:
    return Leaderboard(
        leaderboard_id=LeaderboardId(data["leaderboard_id"]),
        season_code=SeasonCode(data["season_code"]),
        category=data["category"],
        generated_at=_parse_dt(data["generated_at"]),
        min_games=data["min_games"],
        entries=[_leaderboard_entry_from_dict(e) for e in data.get("entries", [])],
    )


# ---------------------------------------------------------------------------
# PlayerRating
# ---------------------------------------------------------------------------

def rating_to_dict(rating: PlayerRating) -> Dict[str, Any]:
    return {
        "player_external_id": str(rating.player_external_id),
        "season_code": str(rating.season_code),
        "rating_value": rating.rating_value.value,
        "rating_version": str(rating.rating_version),
        "calculated_at": _iso(rating.calculated_at),
        "source_stats": rating.source_stats,
    }


def rating_from_dict(data: Dict[str, Any]) -> PlayerRating:
    return PlayerRating(
        player_external_id=ExternalId(data["player_external_id"]),
        season_code=SeasonCode(data["season_code"]),
        rating_value=RatingValue(data["rating_value"]),
        rating_version=RatingVersion(data["rating_version"]),
        calculated_at=_parse_dt(data["calculated_at"]),
        source_stats=list(data.get("source_stats", [])),
    )


# ---------------------------------------------------------------------------
# Publication
# ---------------------------------------------------------------------------

def publication_to_dict(publication: Publication) -> Dict[str, Any]:
    return {
        "publication_id": str(publication.publication_id),
        "title": publication.title,
        "content": publication.content,
        "template_id": publication.template_id,
        "references": publication.references,
        "created_at": _iso(publication.created_at),
        "created_by": _actor_to_dict(publication.created_by),
        "published_at": _iso(publication.published_at),
        "status": publication.status,
        "locale": publication.locale,
    }


def publication_from_dict(data: Dict[str, Any]) -> Publication:
    return Publication(
        publication_id=PublicationId(data["publication_id"]),
        title=data["title"],
        content=data["content"],
        template_id=data["template_id"],
        references=list(data.get("references", [])),
        created_at=_parse_dt(data["created_at"]),
        created_by=_actor_from_dict(data.get("created_by")),
        published_at=_parse_dt(data.get("published_at")),
        status=data.get("status", "DRAFT"),
        locale=data.get("locale"),
    )


# ---------------------------------------------------------------------------
# registry + public API
# ---------------------------------------------------------------------------

_SERIALIZERS: Dict[str, Tuple[Callable[[Any], Dict[str, Any]], Callable[[Dict[str, Any]], Any]]] = {
    "Match": (match_to_dict, match_from_dict),
    "Player": (player_to_dict, player_from_dict),
    "Team": (team_to_dict, team_from_dict),
    "Competition": (competition_to_dict, competition_from_dict),
    "CorrectionProposal": (correction_to_dict, correction_from_dict),
    "StandingSnapshot": (standing_to_dict, standing_from_dict),
    "Leaderboard": (leaderboard_to_dict, leaderboard_from_dict),
    "PlayerRating": (rating_to_dict, rating_from_dict),
    "Publication": (publication_to_dict, publication_from_dict),
}

SUPPORTED_TYPES: Tuple[str, ...] = tuple(_SERIALIZERS.keys())


def serialize(aggregate: Any) -> Dict[str, Any]:
    """Return a JSON-safe, self-describing envelope for a domain aggregate."""
    kind = type(aggregate).__name__
    if kind not in _SERIALIZERS:
        raise ValueError(f"No serializer registered for {kind}")
    encoder, _ = _SERIALIZERS[kind]
    return {"type": kind, "data": encoder(aggregate)}


def deserialize(document: Dict[str, Any]) -> Any:
    """Rebuild a domain aggregate from a ``serialize`` envelope."""
    kind = document["type"]
    if kind not in _SERIALIZERS:
        raise ValueError(f"No deserializer registered for {kind}")
    _, decoder = _SERIALIZERS[kind]
    return decoder(document["data"])