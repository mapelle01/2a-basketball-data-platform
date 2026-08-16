"""FASE 24.1 — Production Catalog Backfill.

Populates the ``players``/``teams`` catalog tables for a season from the
canonical entity set (distinct external_ids present in the season's BoxScore
stats projection) plus an official name resolver.

Identity rule (unchanged, canonical):
  * Player identity = ``player_external_id``
  * Team identity   = ``team_external_id``
Names are descriptive attributes only: never used as a key, never used to
merge entities.

Write policy (deterministic, documented):
  * new external_id            -> create (name may be NULL when no official
                                   name is available; documented gap)
  * existing, name NULL/empty  -> fill with the official name if available
  * existing, valid name equal -> skip (no change)
  * existing, valid name other -> preserve existing + record a warning
                                   (a valid existing name is never overwritten)

The backfill is idempotent and re-runnable; a second run with no new official
names reports ``created=0 updated=0 skipped=N errors=0``. It reads season stats
(read-only) and writes ONLY the catalog tables: match/player/team stats,
matches and events are never modified.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Protocol

from ...domain.player.model import Player
from ...domain.team.model import Team
from ...domain.value_objects import ExternalId, PlayerId, SeasonCode, TeamId

# sentinel: entity present in stats but not present in the resolver map
SEASON_NOT_INCLUDED = object()


class CatalogNameResolver(Protocol):
    """Maps external_id -> official name (None when unavailable) for a season."""

    def resolve(self, season_code: SeasonCode) -> Dict[str, Optional[str]]:
        ...


class _EmptyResolver:
    """No official source: every entity is created with name = NULL."""

    def resolve(self, season_code: SeasonCode) -> Dict[str, Optional[str]]:
        return {}


def _empty_name(value: Optional[str]) -> bool:
    return value is None or str(value).strip() == ""


@dataclass
class CatalogBackfillStats:
    created: int = 0
    updated: int = 0
    skipped: int = 0
    errors: int = 0
    warnings: List[str] = field(default_factory=list)


class CatalogBackfillService:
    """Idempotent, deterministic, read/stats + write/catalog-only backfill."""

    def __init__(
        self,
        player_repo,
        team_repo,
        stats_repo,
        *,
        player_names: Optional[CatalogNameResolver] = None,
        team_names: Optional[CatalogNameResolver] = None,
    ) -> None:
        self._players = player_repo
        self._teams = team_repo
        self._stats = stats_repo
        self._player_names = player_names or _EmptyResolver()
        self._team_names = team_names or _EmptyResolver()
        self._dry_run = False

    # ------------------------------------------------------------------ run
    def run(self, season_code: SeasonCode, entities=("players", "teams"),
            dry_run: bool = False) -> CatalogBackfillStats:
        stats = CatalogBackfillStats()
        self._dry_run = dry_run
        if "players" in entities:
            self._backfill_players(season_code, stats)
        if "teams" in entities:
            self._backfill_teams(season_code, stats)
        return stats

    # --------------------------------------------------------------- players
    def _backfill_players(self, season_code: SeasonCode, stats: CatalogBackfillStats) -> None:
        names = self._player_names.resolve(season_code)
        aggregates = self._stats.list_season_player_aggregates(season_code)
        for external_id in sorted(a.player_external_id for a in aggregates):
            try:
                existing = self._players.get_by_external_id(ExternalId(external_id))
                self._upsert_one(
                    stats,
                    repo=self._players,
                    external_id=external_id,
                    official=names.get(external_id, SEASON_NOT_INCLUDED),
                    existing=existing,
                    entity_id_factory=PlayerId,
                    entity_factory=lambda existing_id, name: Player(
                        external_id=ExternalId(external_id),
                        player_id=existing_id,
                        name=name,
                    ),
                )
            except Exception as exc:  # noqa: BLE001 - per-entity isolation
                stats.errors += 1
                stats.warnings.append(f"player {external_id}: {exc}")

    # ------------------------------------------------------------------ teams
    def _backfill_teams(self, season_code: SeasonCode, stats: CatalogBackfillStats) -> None:
        names = self._team_names.resolve(season_code)
        aggregates = self._stats.list_season_team_aggregates(season_code)
        for external_id in sorted(a.team_external_id for a in aggregates):
            try:
                existing = self._teams.get_by_external_id(ExternalId(external_id))
                self._upsert_one(
                    stats,
                    repo=self._teams,
                    external_id=external_id,
                    official=names.get(external_id, SEASON_NOT_INCLUDED),
                    existing=existing,
                    entity_id_factory=TeamId,
                    entity_factory=lambda existing_id, name: Team(
                        external_id=ExternalId(external_id),
                        team_id=existing_id,
                        name=name,
                    ),
                )
            except Exception as exc:  # noqa: BLE001 - per-entity isolation
                stats.errors += 1
                stats.warnings.append(f"team {external_id}: {exc}")

    # ------------------------------------------------------------------ write
    def _upsert_one(self, stats: CatalogBackfillStats, *, repo, external_id: str,
                    official: object, existing, entity_id_factory, entity_factory) -> None:
        official_name = None if official is SEASON_NOT_INCLUDED else official
        if existing is None:
            entity_id = entity_id_factory(str(uuid.uuid4()))
            entity = entity_factory(entity_id, official_name)
            if not self._dry_run:
                repo.upsert_catalog(
                    ExternalId(external_id), entity_id, official_name,
                    _serialize(entity),
                )
            stats.created += 1
            return

        existing_name = existing.name
        if _empty_name(existing_name):
            if _empty_name(official_name):
                stats.skipped += 1
                return
            entity = entity_factory(existing_id_of(existing), official_name)
            if not self._dry_run:
                repo.upsert_catalog(
                    ExternalId(external_id), existing_id_of(existing), official_name,
                    _serialize(entity),
                )
            stats.updated += 1
            return

        # existing valid name: never overwritten
        if official_name is not None and official_name != existing_name:
            stats.warnings.append(
                f"{external_id}: keeping existing name {existing_name!r} "
                f"(official candidate {official_name!r})"
            )
        stats.skipped += 1


def existing_id_of(entity):
    return entity.player_id if isinstance(entity, Player) else entity.team_id


def _serialize(entity):
    if isinstance(entity, Player):
        from ...application.persistence.serialization import player_to_dict
        return json.dumps(player_to_dict(entity))
    from ...application.persistence.serialization import team_to_dict
    return json.dumps(team_to_dict(entity))