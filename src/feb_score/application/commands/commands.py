from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict

from ...domain.value_objects import Actor, CommandMeta


@dataclass(frozen=True)
class BaseCommand:
    command_id: str
    meta: CommandMeta
    actor: Actor
    payload: Dict[str, Any]


@dataclass(frozen=True)
class CreateOrUpdateMatchCommand(BaseCommand):
    pass


@dataclass(frozen=True)
class FinalizeMatchCommand(BaseCommand):
    pass


@dataclass(frozen=True)
class ProposeCorrectionCommand(BaseCommand):
    pass


@dataclass(frozen=True)
class ApproveCorrectionCommand(BaseCommand):
    pass


@dataclass(frozen=True)
class RegisterPlayerToSquadCommand(BaseCommand):
    pass


@dataclass(frozen=True)
class GenerateStandingSnapshotCommand(BaseCommand):
    pass


@dataclass(frozen=True)
class GenerateLeaderboardCommand(BaseCommand):
    pass


@dataclass(frozen=True)
class ComputePlayerRatingCommand(BaseCommand):
    pass


@dataclass(frozen=True)
class CreatePublicationCommand(BaseCommand):
    pass


@dataclass(frozen=True)
class BackfillSeasonCommand(BaseCommand):
    pass


@dataclass(frozen=True)
class UpsertMatchStatsCommand(BaseCommand):
    pass


@dataclass(frozen=True)
class BackfillCatalogCommand(BaseCommand):
    pass


# Versioned command catalog (FASE 11): the stable public surface exposed by the
# HTTP API. The keys are the URL-safe command types; each maps to its Command
# class, which carries the versioned contract name for validation.
COMMANDS: Dict[str, type] = {
    "create_or_update_match": CreateOrUpdateMatchCommand,
    "finalize_match": FinalizeMatchCommand,
    "propose_correction": ProposeCorrectionCommand,
    "approve_correction": ApproveCorrectionCommand,
    "register_player_to_squad": RegisterPlayerToSquadCommand,
    "generate_standing_snapshot": GenerateStandingSnapshotCommand,
    "generate_leaderboard": GenerateLeaderboardCommand,
    "compute_player_rating": ComputePlayerRatingCommand,
    "create_publication": CreatePublicationCommand,
    "backfill_season": BackfillSeasonCommand,
    "upsert_match_stats": UpsertMatchStatsCommand,
    "backfill_catalog": BackfillCatalogCommand,
}
