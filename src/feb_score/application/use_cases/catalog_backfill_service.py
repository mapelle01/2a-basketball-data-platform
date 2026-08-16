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
        external_ids = sorted({a.player_external_id for a in aggregates})
        existing = self._players.get_many_by_external_ids(external_ids)
        writes = self._decide(
            stats, external_ids, names, existing, PlayerId,
            lambda eid, eid_factory, name: Player(external_id=ExternalId(eid), player_id=eid_factory, name=name),
        )
        self._flush(stats, self._players, writes, "player", dry_run=self._dry_run)

    # -------------------------------------------------- teams
    def _backfill_teams(self, season_code: SeasonCode, stats: CatalogBackfillStats) -> None:
        names = self._team_names.resolve(season_code)
        aggregates = self._stats.list_season_team_aggregates(season_code)
        external_ids = sorted({a.team_external_id for a in aggregates})
        existing = self._teams.get_many_by_external_ids(external_ids)
        writes = self._decide(
            stats, external_ids, names, existing, TeamId,
            lambda eid, eid_factory, name: Team(external_id=ExternalId(eid), team_id=eid_factory, name=name),
        )
        self._flush(stats, self._teams, writes, "team", dry_run=self._dry_run)

    # ---------------------------------------------- decide (pure, read-only)
    def _decide(self, stats: CatalogBackfillStats, external_ids, names, existing,
                id_factory, entity_factory) -> List[tuple]:
        """Classify each external_id under the documented write policy.

        Returns a list of ``(external_id, entity_id, name, data)`` rows to write
        (empty in the skipped/keep-existing cases). The actual DB write happens
        once, in bulk, in ``_flush`` — so the policy decision is made in memory
        against the snapshot returned by the single ``get_many_by_external_ids``
        call (FASE 24.2: avoids one connection per entity over the tunnel).
        """
        writes: List[tuple] = []
        for external_id in external_ids:
            official = names.get(external_id, SEASON_NOT_INCLUDED)
            official_name = None if official is SEASON_NOT_INCLUDED else official
            cur = existing.get(external_id)
            try:
                if cur is None:
                    entity_id = id_factory(str(uuid.uuid4()))
                    writes.append((external_id, str(entity_id), official_name, _serialize(entity_factory(external_id, entity_id, official_name))))
                    stats.created += 1
                    continue
                if _empty_name(cur.name):
                    if _empty_name(official_name):
                        stats.skipped += 1
                        continue
                    entity = entity_factory(external_id, existing_id_of(cur), official_name)
                    writes.append((external_id, str(existing_id_of(cur)), official_name, _serialize(entity)))
                    stats.updated += 1
                    continue
                # existing valid name: never overwritten
                if official_name is not None and official_name != cur.name:
                    stats.warnings.append(f"{external_id}: keeping existing name {cur.name!r} (official candidate {official_name!r})")
                stats.skipped += 1
            except Exception as exc:  # noqa: BLE001 - per-entity isolation
                stats.errors += 1
                stats.warnings.append(f"{external_id}: {exc}")
        return writes

    # ---------------------------------------------------- single bulk write
    def _flush(self, stats: CatalogBackfillStats, repo, writes, label: str,
               dry_run: bool) -> None:
        if dry_run or not writes:
            return
        try:
            repo.upsert_catalog_many(writes)
        except Exception as exc:  # noqa: BLE001 - whole-batch classification
            stats.errors += len(writes)
            stats.warnings.append(f"{label} batch upsert failed: {exc}")


def existing_id_of(entity):
    return entity.player_id if isinstance(entity, Player) else entity.team_id


def _serialize(entity):
    if isinstance(entity, Player):
        from ...application.persistence.serialization import player_to_dict
        return json.dumps(player_to_dict(entity))
    from ...application.persistence.serialization import team_to_dict
    return json.dumps(team_to_dict(entity))