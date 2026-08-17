from __future__ import annotations

import os
import uuid
from datetime import datetime
from typing import Dict, Iterable, List, Optional


def parse_iso_datetime(value: str) -> datetime:
    if value.endswith("Z"):
        return datetime.fromisoformat(value[:-1])
    return datetime.fromisoformat(value)

from ..commands.commands import (
    ApproveCorrectionCommand,
    BackfillCatalogCommand,
    BackfillSeasonCommand,
    ComputePlayerRatingCommand,
    CreateOrUpdateMatchCommand,
    CreatePublicationCommand,
    FinalizeMatchCommand,
    GenerateLeaderboardCommand,
    GenerateStandingSnapshotCommand,
    ProposeCorrectionCommand,
    RegisterPlayerToSquadCommand,
    UpsertMatchStatsCommand,
)
from ..repositories.interfaces import (
    CompetitionRepository,
    CorrectionRepository,
    IdempotencyRepository,
    LeaderboardRepository,
    MatchRepository,
    MatchStatsRepository,
    PlayerRepository,
    PublicationRepository,
    RatingRepository,
    StandingRepository,
    TeamRepository,
)
from ...domain.value_objects import (
    Actor,
    CompetitionId,
    CorrectionProposalId,
    ExternalId,
    EventMeta,
    MatchId,
    PublicationId,
    RatingVersion,
    SeasonCode,
    PeriodScore,
    ScoreSummary,
)
from ...domain.correction.model import CorrectionProposal
from ...domain.events import (
    CorrectionProposed,
    CorrectionRejected,
    DomainAlert,
    LeaderboardGenerated,
    MatchUpserted,
    MatchValidationStarted,
    MatchValidated,
    PublicationCreated,
    SeasonBackfillCompleted,
    SeasonBackfillStarted,
    StandingSnapshotGenerated,
    PlayerRegistered,
    PlayerRatingComputed,
    PlayerMilestoneReached,
    ValidationFailed,
)
from ...domain.leaderboard.model import Leaderboard
from ...domain.match.model import Match
from ...domain.publication.model import Publication
from ...domain.ratings.model import PlayerRating
from ...domain.standings.model import StandingSnapshot
from ...domain.statistics.model import PlayerStats, TeamStats
from ...domain.errors import EntityNotFound, MatchNotFound
from ..validation import contract_validated


class CreateOrUpdateMatchHandler:
    def __init__(self, match_repository: MatchRepository, idempotency_repository: IdempotencyRepository | None = None):
        self.match_repository = match_repository
        self.idempotency_repository = idempotency_repository

    @contract_validated("commands/create_or_update_match.v1.json")
    def handle(self, command: CreateOrUpdateMatchCommand) -> List[object]:
        if self.idempotency_repository and self.idempotency_repository.has_processed(command.command_id):
            return []

        payload = command.payload
        external_match_id = ExternalId(payload["external_id"])
        source = payload["source"] if "source" in payload else {}
        venue = payload.get("venue")
        raw = payload.get("raw")
        existing = self.match_repository.get_by_external_id(external_match_id)

        if existing is None:
            match = Match.create(
                external_id=external_match_id,
                match_id=MatchId(str(uuid.uuid4())),
                competition_id=CompetitionId(payload.get("competition_id", "unknown")),
                season_code=SeasonCode(payload["season_code"]),
                round_number=int(payload.get("round_number", 0)),
                home_team_id=ExternalId(payload["home_team"]["external_id"]),
                away_team_id=ExternalId(payload["away_team"]["external_id"]),
                scheduled_at=parse_iso_datetime(payload["scheduled_at"]),
                source=source,
                venue=venue,
                raw=raw,
            )
        else:
            match = existing
            updates: Dict[str, object] = {
                "competition_id": payload.get("competition_id", str(match.competition_id)),
                "season_code": payload["season_code"],
                "round_number": payload.get("round_number", match.round_number),
                "home_team_id": payload["home_team"]["external_id"],
                "away_team_id": payload["away_team"]["external_id"],
                "scheduled_at": parse_iso_datetime(payload["scheduled_at"]),
                "status": match.status,
                "source": source,
            }
            if venue is not None:
                updates["venue"] = venue
            if raw is not None:
                updates["raw"] = raw
            match.upsert(**updates)

        self.match_repository.save(match)
        if self.idempotency_repository:
            self.idempotency_repository.mark_processed(command.command_id)
        events = match.collect_events()
        match.clear_events()
        return events


class UpsertMatchStatsHandler:
    """FASE 21.B3 — record provisional BoxScore team/player stats on a match.

    Stats belong to the Match aggregate (Match.record_stats) and are ALSO
    persisted as a queryable projection (MatchStatsRepository) keyed by FEB
    external ids, so reads are indexed and re-ingestion cannot duplicate rows.
    """

    def __init__(
        self,
        match_repository: MatchRepository,
        stats_repository: MatchStatsRepository,
        idempotency_repository: IdempotencyRepository | None = None,
    ):
        self.match_repository = match_repository
        self.stats_repository = stats_repository
        self.idempotency_repository = idempotency_repository

    @contract_validated("commands/upsert_match_stats.v1.json")
    def handle(self, command: UpsertMatchStatsCommand) -> List[object]:
        if self.idempotency_repository and self.idempotency_repository.has_processed(command.command_id):
            return []

        payload = command.payload
        match = self.match_repository.get_by_external_id(ExternalId(payload["match_external_id"]))
        if match is None:
            raise MatchNotFound("Match not found")

        home_team_stats = self._team_stats(payload.get("home_team_stats"))
        away_team_stats = self._team_stats(payload.get("away_team_stats"))
        player_stats = tuple(self._player_stats(ps) for ps in payload.get("player_stats", []))

        match.record_stats(
            home_team_stats=home_team_stats,
            away_team_stats=away_team_stats,
            player_stats=player_stats,
            actor_id=command.actor.id,
        )

        season_code = SeasonCode(payload["season_code"])
        self.match_repository.save(match)
        team_stats = [ts for ts in (home_team_stats, away_team_stats) if ts is not None]
        self.stats_repository.save_team_stats(str(match.external_id), season_code, team_stats)
        self.stats_repository.save_player_stats(str(match.external_id), season_code, player_stats)
        if self.idempotency_repository:
            self.idempotency_repository.mark_processed(command.command_id)
        events = match.collect_events()
        match.clear_events()
        return events

    @staticmethod
    def _team_stats(raw: Optional[Dict[str, object]]) -> Optional[TeamStats]:
        if raw is None:
            return None
        return TeamStats(
            team_external_id=raw["team_external_id"],
            points_for=int(raw["points_for"]),
            points_against=int(raw["points_against"]),
            field_goals_made=int(raw["field_goals_made"]),
            field_goals_attempted=int(raw["field_goals_attempted"]),
            three_points_made=int(raw["three_points_made"]),
            three_points_attempted=int(raw["three_points_attempted"]),
            free_throws_made=int(raw["free_throws_made"]),
            free_throws_attempted=int(raw["free_throws_attempted"]),
            turnovers=int(raw["turnovers"]),
            rebounds=int(raw["rebounds"]),
        )

    @staticmethod
    def _player_stats(raw: Dict[str, object]) -> PlayerStats:
        played_at = raw.get("played_at")
        return PlayerStats(
            player_external_id=str(raw["player_external_id"]),
            team_external_id=str(raw["team_external_id"]),
            points=int(raw["points"]),
            rebounds=int(raw["rebounds"]),
            assists=int(raw["assists"]),
            steals=int(raw.get("steals", 0)),
            blocks=int(raw.get("blocks", 0)),
            turnovers=int(raw.get("turnovers", 0)),
            minutes=float(raw.get("minutes", 0.0)),
            played_at=parse_iso_datetime(played_at) if played_at else None,
        )


class FinalizeMatchHandler:
    def __init__(self, match_repository: MatchRepository, idempotency_repository: IdempotencyRepository | None = None):
        self.match_repository = match_repository
        self.idempotency_repository = idempotency_repository

    @contract_validated("commands/finalize_match.v1.json")
    def handle(self, command: FinalizeMatchCommand) -> List[object]:
        if self.idempotency_repository and self.idempotency_repository.has_processed(command.command_id):
            return []

        payload = command.payload
        external_match_id = ExternalId(payload["match_external_id"])
        match = self.match_repository.get_by_external_id(external_match_id)
        if match is None:
            raise MatchNotFound("Match not found")

        started_event = MatchValidationStarted(
            event_id=str(uuid.uuid4()),
            meta=EventMeta(version="1.0", produced_at=datetime.utcnow()),
            source={"origin": "system", "actor": {"id": command.actor.id}},
            payload={
                "external_id": str(external_match_id),
                "match_uuid": str(match.match_id),
                "initiator": command.actor.id,
            },
        )

        try:
            strict = payload.get("validation_context", {}).get("strict", False)
            match.finalize(finalized_at=command.meta.issued_at, actor_id=command.actor.id, strict=strict)
        except Exception as exc:
            failed_event = ValidationFailed(
                event_id=str(uuid.uuid4()),
                meta=EventMeta(version="1.0", produced_at=datetime.utcnow()),
                source={"origin": "system", "actor": {"id": command.actor.id}},
                payload={
                    "external_id": str(external_match_id),
                    "match_uuid": str(match.match_id) if match else "",
                    "errors": [str(exc)],
                },
            )
            return [started_event, failed_event]

        validated_event = MatchValidated(
            event_id=str(uuid.uuid4()),
            meta=EventMeta(version="1.0", produced_at=datetime.utcnow()),
            source={"origin": "system", "actor": {"id": command.actor.id}},
            payload={
                "external_id": str(external_match_id),
                "match_uuid": str(match.match_id),
                "validation_result": "OK",
            },
        )

        self.match_repository.save(match)
        if self.idempotency_repository:
            self.idempotency_repository.mark_processed(command.command_id)
        events = [started_event, validated_event] + match.collect_events()
        match.clear_events()
        return events


class ProposeCorrectionHandler:
    def __init__(self, correction_repository: CorrectionRepository, idempotency_repository: IdempotencyRepository | None = None):
        self.correction_repository = correction_repository
        self.idempotency_repository = idempotency_repository

    @contract_validated("commands/propose_correction.v1.json")
    def handle(self, command: ProposeCorrectionCommand) -> object:
        if self.idempotency_repository and self.idempotency_repository.has_processed(command.command_id):
            return []

        payload = command.payload
        # Identity attribution (id) may come from the payload, but the ROLE is
        # always the authenticated actor's: a client cannot forge role=admin here.
        proposed_by = Actor(id=payload["proposed_by"]["id"], role=command.actor.role)
        proposal = CorrectionProposal(
            proposal_id=CorrectionProposalId(command.command_id),
            match_external_id=ExternalId(payload["match_external_id"]),
            proposed_by=proposed_by,
            proposed_at=datetime.utcnow(),
            reason=payload["reason"],
            changes=payload["changes"],
        )
        self.correction_repository.save(proposal)
        if self.idempotency_repository:
            self.idempotency_repository.mark_processed(command.command_id)
        return CorrectionProposed(
            event_id=command.command_id,
            meta=EventMeta(version="1.0", produced_at=datetime.utcnow()),
            source={"origin": "admin", "actor": {"id": command.actor.id}},
            payload={
                "proposal_id": str(proposal.proposal_id),
                "match_external_id": str(proposal.match_external_id),
                "proposed_by": {"id": proposal.proposed_by.id},
                "summary": proposal.reason,
                "changes": proposal.changes,
            },
        )


class ApproveCorrectionHandler:
    def __init__(
        self,
        correction_repository: CorrectionRepository,
        match_repository: MatchRepository,
        idempotency_repository: IdempotencyRepository | None = None,
    ):
        self.correction_repository = correction_repository
        self.match_repository = match_repository
        self.idempotency_repository = idempotency_repository

    @contract_validated("commands/approve_correction.v1.json")
    def handle(self, command: ApproveCorrectionCommand) -> List[object]:
        if self.idempotency_repository and self.idempotency_repository.has_processed(command.command_id):
            return []

        payload = command.payload
        proposal = self.correction_repository.get_by_id(payload["proposal_id"])
        if proposal is None:
            raise EntityNotFound("Correction proposal not found")

        # The approver ROLE comes from the authenticated actor (the API already
        # gatekept approve_correction to admins). The payload's declared role is
        # NEVER trusted: a client cannot approve by sending approved_by.role=admin.
        approver = Actor(id=payload["approved_by"]["id"], role=command.actor.role)
        match = self.match_repository.get_by_external_id(proposal.match_external_id)
        if match is None:
            raise MatchNotFound("Match not found for correction")

        approved_at = parse_iso_datetime(payload.get("approved_at", datetime.utcnow().isoformat()))
        previous_version = match.version
        proposal.ensure_can_be_approved_by(approver)

        match.apply_correction(
            correction_id=payload["proposal_id"],
            changes=proposal.changes,
            approved_at=approved_at,
            approver_id=approver.id,
            reason=proposal.reason,
        )

        proposal.approve(
            approver=approver,
            approved_at=approved_at,
            previous_version=str(previous_version),
            new_version=str(match.version),
            comment=payload.get("comment"),
        )
        self.correction_repository.save(proposal)
        self.match_repository.save(match)
        if self.idempotency_repository:
            self.idempotency_repository.mark_processed(command.command_id)

        events: List[object] = []
        events.extend(match.collect_events())
        events.extend(proposal.collect_events())
        proposal.clear_events()
        match.clear_events()
        return events


class RegisterPlayerToSquadHandler:
    def __init__(
        self,
        player_repository: PlayerRepository,
        team_repository: TeamRepository,
    ):
        self.player_repository = player_repository
        self.team_repository = team_repository

    @contract_validated("commands/register_player_to_squad.v1.json")
    def handle(self, command: RegisterPlayerToSquadCommand) -> object:
        payload = command.payload
        player = self.player_repository.get_by_external_id(ExternalId(payload["player_external_id"]))
        if player is None:
            raise EntityNotFound("Player not found")

        team = self.team_repository.get_by_external_id(ExternalId(payload["team_external_id"]))
        if team is None:
            raise EntityNotFound("Team not found")

        season_code = SeasonCode(payload["season_code"])
        registered_from = parse_iso_datetime(payload["registered_from"]).date()
        registered_to = parse_iso_datetime(payload["registered_to"]).date() if payload.get("registered_to") else None
        dorsal = int(payload.get("dorsal")) if payload.get("dorsal") is not None else None
        role = payload.get("role")
        registration_id = str(uuid.uuid4())

        player.ensure_can_register_for_team(
            team_external_id=str(team.external_id),
            season_code=season_code,
            dorsal=dorsal,
        )
        team.ensure_can_add_player_registration(
            player_external_id=str(player.external_id),
            season_code=season_code,
            dorsal=dorsal,
        )

        player.register_for_team(
            team_external_id=str(team.external_id),
            season_code=season_code,
            dorsal=dorsal,
            registered_at=registered_from,
            registered_to=registered_to,
            role=role,
            registration_id=registration_id,
        )
        team.add_player_registration(
            player_external_id=str(player.external_id),
            season_code=season_code,
            dorsal=dorsal,
            registration_id=registration_id,
        )

        self.player_repository.save(player)
        self.team_repository.save(team)

        event_payload: Dict[str, object] = {
            "registration_id": registration_id,
            "player_external_id": str(player.external_id),
            "team_external_id": str(team.external_id),
            "season_code": str(season_code),
            "registered_from": payload["registered_from"],
        }
        if dorsal is not None:
            event_payload["dorsal"] = str(dorsal)
        if payload.get("registered_to"):
            event_payload["registered_to"] = payload["registered_to"]

        return PlayerRegistered(
            event_id=str(uuid.uuid4()),
            meta=EventMeta(version="1.0", produced_at=datetime.utcnow()),
            source={"origin": "admin", "actor": {"id": command.actor.id}},
            payload=event_payload,
        )


class GenerateStandingSnapshotHandler:
    def __init__(self, standing_repository: StandingRepository, match_repository: MatchRepository, idempotency_repository: IdempotencyRepository | None = None):
        self.standing_repository = standing_repository
        self.match_repository = match_repository
        self.idempotency_repository = idempotency_repository

    @contract_validated("commands/generate_standing_snapshot.v1.json")
    def handle(self, command: GenerateStandingSnapshotCommand) -> object:
        if self.idempotency_repository and self.idempotency_repository.has_processed(command.command_id):
            return []

        payload = command.payload
        competition_id = CompetitionId(payload.get("competition_id", "unknown"))
        season_code = SeasonCode(payload["season_code"])
        snapshot = StandingSnapshot.from_matches(
            competition_id=competition_id,
            season_code=season_code,
            matches=self.match_repository.list_by_season(competition_id, season_code),
            rules_version=payload["rules_version"],
            generated_at=parse_iso_datetime(payload["as_of"]),
            description=payload.get("description"),
        )
        self.standing_repository.save(snapshot)
        if self.idempotency_repository:
            self.idempotency_repository.mark_processed(command.command_id)
        return StandingSnapshotGenerated(
            event_id=str(snapshot.snapshot_id.value),
            meta=EventMeta(version="1.0", produced_at=datetime.utcnow()),
            source={"origin": "system", "actor": {"id": command.actor.id}},
            payload={
                "snapshot_id": str(snapshot.snapshot_id),
                "competition_id": str(snapshot.competition_id),
                "season_code": str(snapshot.season_code),
                "as_of": snapshot.generated_at.isoformat(),
                "matches_included_count": snapshot.matches_count,
                "rules_version": snapshot.rules_version,
            },
        )


class GenerateLeaderboardHandler:
    def __init__(
        self,
        match_repository: MatchRepository,
        leaderboard_repository: LeaderboardRepository | None = None,
        idempotency_repository: IdempotencyRepository | None = None,
    ):
        self.match_repository = match_repository
        self.leaderboard_repository = leaderboard_repository
        self.idempotency_repository = idempotency_repository

    @contract_validated("commands/generate_leaderboard.v1.json")
    def handle(self, command: GenerateLeaderboardCommand) -> object:
        if self.idempotency_repository and self.idempotency_repository.has_processed(command.command_id):
            return []

        payload = command.payload
        season_code = SeasonCode(payload["season_code"])
        competition_id = CompetitionId(payload.get("competition_id", "unknown"))
        leaderboard = Leaderboard.from_matches(
            season_code=season_code,
            category=payload["category"],
            matches=self.match_repository.list_by_season(competition_id, season_code),
            min_games=payload.get("min_games", 0),
            top_n=payload.get("top_n", 100),
            generated_at=datetime.utcnow(),
        )
        if self.leaderboard_repository:
            self.leaderboard_repository.save(leaderboard)
        if self.idempotency_repository:
            self.idempotency_repository.mark_processed(command.command_id)
        return LeaderboardGenerated(
            event_id=str(uuid.uuid4()),
            meta=EventMeta(version="1.0", produced_at=datetime.utcnow()),
            source={"origin": "system", "actor": {"id": command.actor.id}},
            payload={
                "leaderboard_id": str(leaderboard.leaderboard_id),
                "season_code": str(season_code),
                "category": payload["category"],
                "generated_at": leaderboard.generated_at.isoformat(),
                "entries_count": len(leaderboard.entries),
            },
        )


class ComputePlayerRatingHandler:
    def __init__(
        self,
        match_repository: MatchRepository,
        rating_repository: RatingRepository,
        idempotency_repository: IdempotencyRepository | None = None,
    ):
        self.match_repository = match_repository
        self.rating_repository = rating_repository
        self.idempotency_repository = idempotency_repository

    @contract_validated("commands/compute_player_rating.v1.json")
    def handle(self, command: ComputePlayerRatingCommand) -> List[object]:
        if self.idempotency_repository and self.idempotency_repository.has_processed(command.command_id):
            return []

        payload = command.payload
        player_external_id = ExternalId(payload["player_external_id"])
        season_code = SeasonCode(payload["season_code"])
        competition_id = CompetitionId(payload.get("competition_id", "unknown"))
        matches = self.match_repository.list_by_season(competition_id, season_code)

        stats: List[PlayerStats] = []
        for match in matches:
            for player_stat in match.player_stats:
                if player_stat.player_external_id == payload["player_external_id"]:
                    stats.append(
                        PlayerStats(
                            **{**player_stat.to_dict(), "played_at": match.scheduled_at}
                        )
                    )

        from ...domain.ratings.service import RatingComputationService

        service = RatingComputationService()
        rating = service.compute_and_evaluate(
            player_external_id=player_external_id,
            season_code=season_code,
            stats=stats,
            rating_version=RatingVersion(payload["rating_version"]),
            calculated_at=command.meta.issued_at,
            actor_id=command.actor.id,
            window=payload.get("window", "all"),
        )
        self.rating_repository.save(rating)
        if self.idempotency_repository:
            self.idempotency_repository.mark_processed(command.command_id)

        events = rating.collect_events()
        rating.clear_events()
        return events


class CreatePublicationHandler:
    def __init__(self, publication_repository: PublicationRepository):
        self.publication_repository = publication_repository

    @contract_validated("commands/create_publication.v1.json")
    def handle(self, command: CreatePublicationCommand) -> List[object]:
        payload = command.payload
        references = []
        if payload.get("payload_refs"):
            refs = payload["payload_refs"]
            if refs.get("match_external_id"):
                references.append({"type": "match", "id": refs["match_external_id"]})
            if refs.get("snapshot_ref"):
                snapshot_ref = refs["snapshot_ref"]
                references.append({"type": snapshot_ref["type"], "id": snapshot_ref["snapshot_id"]})

        publication = Publication(
            publication_id=PublicationId(command.command_id),
            title=f"Publication for {payload.get('template_id')}",
            content="Automated publication content",
            template_id=payload["template_id"],
            references=references,
        )
        publication.create(
            creator=command.actor,
            created_at=parse_iso_datetime(payload["scheduled_at"]),
            locale=payload.get("locale"),
        )
        self.publication_repository.save(publication)
        events = publication.collect_events()
        publication.clear_events()
        return events


class BackfillSeasonHandler:
    def __init__(
        self,
        competition_repository: CompetitionRepository,
    ):
        self.competition_repository = competition_repository

    @contract_validated("commands/backfill_season.v1.json")
    def handle(self, command: BackfillSeasonCommand) -> List[object]:
        payload = command.payload
        season_code = SeasonCode(payload["season_code"])
        competition = None
        competition_id = payload.get("competition_id")
        if competition_id is not None:
            competition = self.competition_repository.get_by_external_id(ExternalId(competition_id))
            if competition is None:
                raise EntityNotFound("Competition not found")
            if competition.get_season(season_code) is None:
                raise EntityNotFound("Season not found")

        started_payload: Dict[str, object] = {"season_code": str(season_code)}
        completed_payload: Dict[str, object] = {"season_code": str(season_code)}
        if payload.get("from_round") is not None:
            started_payload["from_round"] = payload["from_round"]
            completed_payload["from_round"] = payload["from_round"]
        if payload.get("to_round") is not None:
            started_payload["to_round"] = payload["to_round"]
            completed_payload["to_round"] = payload["to_round"]
        if competition is not None:
            started_payload["competition_external_id"] = str(competition.external_id)
            completed_payload["competition_external_id"] = str(competition.external_id)

        request_id = str(uuid.uuid4())
        started_payload["request_id"] = request_id
        started_payload["requested_by"] = {"id": command.actor.id}
        completed_payload["request_id"] = request_id
        completed_payload["status"] = "ok"

        started = SeasonBackfillStarted(
            event_id=str(uuid.uuid4()),
            meta=EventMeta(version="1.0", produced_at=datetime.utcnow()),
            source={"origin": "admin", "actor": {"id": command.actor.id}},
            payload=started_payload,
        )
        completed = SeasonBackfillCompleted(
            event_id=str(uuid.uuid4()),
            meta=EventMeta(version="1.0", produced_at=datetime.utcnow()),
            source={"origin": "system", "actor": {"id": command.actor.id}},
            payload=completed_payload,
        )
        return [started, completed]


class _ServerTeamNameResolver:
    """Official team names via the public FEB calendar.

    Reuses the standalone backfill script policy (``resolve_team_names_from_calendar``:
    most frequent name per team, ties broken by the lexicographically smallest name)
    so the name policy stays in ONE place. The calendar is public (no token).
    """

    def __init__(self, match_repo, season_code: str) -> None:
        self._match_repo = match_repo
        self._season = season_code

    def resolve(self, season_code):
        from .player_name_resolver import _import_feb  # noqa: PLC0415 (lazy, script sibling)

        _import_feb()  # puts scripts/feb on sys.path
        import backfill_catalog as BC  # noqa: PLC0415 (sibling script)
        import discover_matches as DM  # noqa: PLC0415 (calendar fetch)

        matches = [
            (str(m.external_id), str(m.home_team_id), str(m.away_team_id))
            for m in self._match_repo.search(SeasonCode(self._season))
        ]
        html: Optional[Dict[str, str]] = None
        if os.environ.get("FEB_CALENDAR_HTML") == "offline":
            html = {}  # deterministic empty (tests / no network)
        return BC.resolve_team_names_from_calendar(self._season, matches, html)


class BackfillCatalogHandler:
    """FASE 25 — Admin command to backfill the players/teams catalog for a season.

    Runs ``CatalogBackfillService`` (canonical entity set = distinct external_ids
    in the season stats projection; deterministic write policy; idempotent). Player
    names come from the official FEB BoxScore (auto-token, no manual rotation);
    team names from the public FEB calendar. Resolvers are injectable for tests;
    when the FEB connector is unavailable the backfill still runs with NULL names
    (documented gap), never inventing names.

    The command runs inside the CommandRunner's single unit of work, so the bulk
    read + batch upsert share one connection (FASE 24.2 semantics).
    """

    def __init__(
        self,
        match_repo,
        stats_repo,
        player_repo,
        team_repo,
        *,
        player_names=None,
        team_names=None,
    ) -> None:
        self._match_repo = match_repo
        self._stats_repo = stats_repo
        self._player_repo = player_repo
        self._team_repo = team_repo
        self._player_names = player_names
        self._team_names = team_names

    @contract_validated("commands/backfill_catalog.v1.json")
    def handle(self, command: BackfillCatalogCommand) -> List[object]:
        payload = command.payload
        season = SeasonCode(payload["season_code"])
        entity = payload.get("entity", "both")
        dry_run = bool(payload.get("dry_run", False))

        do_players = entity in ("players", "both")
        do_teams = entity in ("teams", "both")
        entities = tuple(
            name for name, on in (("players", do_players), ("teams", do_teams)) if on
        )

        player_names = self._player_names
        if player_names is None and do_players:
            from .player_name_resolver import (  # noqa: PLC0415 (lazy, connector may be absent)
                OfficialPlayerNameResolver,
            )

            token = os.environ.get("FEB_TOKEN") or None  # optional override; auto-token otherwise
            player_names = OfficialPlayerNameResolver(
                self._match_repo, self._stats_repo, str(season), token=token
            )

        team_names = self._team_names
        if team_names is None and do_teams:
            team_names = _ServerTeamNameResolver(self._match_repo, str(season))

        from .catalog_backfill_service import (  # noqa: PLC0415
            CatalogBackfillService,
        )

        svc = CatalogBackfillService(
            self._player_repo,
            self._team_repo,
            self._stats_repo,
            player_names=player_names,
            team_names=team_names,
        )
        stats = svc.run(season, entities=entities, dry_run=dry_run)
        return []  # no domain events; results are reported via the response/logs
