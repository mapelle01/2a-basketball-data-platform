"""Fill the players catalog with the bio the boxscore never carries.

Position, height, birth date (and birth city) and nationality live on the public
FEB player profile — reached by the very link each boxscore row already gives
us. This service walks the players who have stats in a season, resolves their
bio and persists what is missing.

Write policy (mirrors the name policy so the catalog behaves consistently):
  * empty field  -> fill with the official value
  * field set    -> KEEP the existing value (never overwritten, never "corrected")
  * no value available -> leave as is
So a re-run with unchanged data writes nothing, and a human correction made in
the platform survives every subsequent backfill.

Weight is not handled: FEB publishes it as "- Kg" for everyone. Relations
(siblings, sons of…) are NOT a field on the source and are only ever inferable,
so they are deliberately out of scope — inferring them would breach "no
inventar".
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Protocol

from ...domain.player.model import Player
from ...domain.value_objects import SeasonCode

# The bio attributes this service manages, in Player-attribute terms.
BIO_FIELDS = ("position", "height_cm", "birth_date", "birth_place", "nationality")


@dataclass
class BioBackfillStats:
    seen: int = 0
    updated: int = 0
    unchanged: int = 0
    unresolved: int = 0
    errors: int = 0
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "seen": self.seen, "updated": self.updated, "unchanged": self.unchanged,
            "unresolved": self.unresolved, "errors": self.errors,
            "warnings": list(self.warnings),
        }


class PlayerBioResolver(Protocol):
    """Maps player_external_id -> a mapping of BIO_FIELDS (missing keys = unknown)."""

    def resolve(self, player_external_id: str) -> Optional[Dict[str, Any]]:
        ...


class PublicProfileBioResolver:
    """Resolves bios from the public FEB player profile (no token).

    Needs each player's team, because the profile URL is keyed by both ids; the
    team comes from the player's own stats rows for that season.
    """

    def __init__(self, stats_repo, season_code: str, *, max_workers: int = 6,
                 fetch: Optional[Callable[[str, str], str]] = None,
                 parse: Optional[Callable[[str, str], Any]] = None) -> None:
        self._stats = stats_repo
        self._season = season_code
        self._max_workers = max_workers
        self._fetch = fetch
        self._parse = parse

    def _load(self):
        if self._fetch is not None and self._parse is not None:
            return
        import os
        import sys

        scripts_dir = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "scripts", "feb")
        )
        if scripts_dir not in sys.path:
            sys.path.insert(0, scripts_dir)
        import parse_player_profile as PPP  # noqa: PLC0415

        self._fetch = self._fetch or (lambda pid, tid: PPP.fetch_player_page(pid, tid))
        self._parse = self._parse or (lambda html, pid: PPP.parse_player_profile(html, pid))

    def _team_of(self, player_external_id: str) -> Optional[str]:
        teams = list(self._stats.list_player_season_teams(
            player_external_id, SeasonCode(self._season)))
        return teams[0] if teams else None

    def resolve(self, player_external_id: str) -> Optional[Dict[str, Any]]:
        self._load()
        team_id = self._team_of(player_external_id)
        if team_id is None:
            return None
        try:
            bio = self._parse(self._fetch(player_external_id, team_id), player_external_id)
        except Exception:  # noqa: BLE001 — one unreachable profile never aborts the run
            return None
        if bio is None or bio.is_empty:
            return None
        return {
            "position": bio.position,
            "height_cm": bio.height_cm,
            "birth_date": bio.birth_date,
            "birth_place": bio.birth_place,
            "nationality": bio.nationality,
        }

    def resolve_many(self, player_external_ids) -> Dict[str, Optional[Dict[str, Any]]]:
        ids = list(player_external_ids)
        if not ids:
            return {}
        with ThreadPoolExecutor(max_workers=self._max_workers) as pool:
            return dict(zip(ids, pool.map(self.resolve, ids)))


class PlayerBioBackfillService:
    def __init__(self, player_repo, stats_repo, resolver) -> None:
        self._players = player_repo
        self._stats = stats_repo
        self._resolver = resolver

    def run(self, season_code: SeasonCode, *, dry_run: bool = False,
            limit: Optional[int] = None) -> BioBackfillStats:
        stats = BioBackfillStats()
        aggregates = list(self._stats.list_season_player_aggregates(season_code))
        ids = sorted({a.player_external_id for a in aggregates})
        if limit is not None:
            ids = ids[:limit]

        resolve_many = getattr(self._resolver, "resolve_many", None)
        bios = resolve_many(ids) if resolve_many else {i: self._resolver.resolve(i) for i in ids}

        for external_id in ids:
            stats.seen += 1
            bio = bios.get(external_id)
            if not bio:
                stats.unresolved += 1
                continue
            try:
                player = self._lookup(external_id)
                if player is None:  # not in the catalog yet — names backfill first
                    stats.unresolved += 1
                    continue
                if self._apply(player, bio):
                    if not dry_run:
                        self._players.save(player)
                    stats.updated += 1
                else:
                    stats.unchanged += 1
            except Exception as exc:  # noqa: BLE001 — isolate one bad player
                stats.errors += 1
                stats.warnings.append(f"{external_id}: {str(exc)[:120]}")
        return stats

    def _lookup(self, external_id: str) -> Optional[Player]:
        from ...domain.value_objects import ExternalId

        return self._players.get_by_external_id(ExternalId(external_id))

    @staticmethod
    def _apply(player: Player, bio: Dict[str, Any]) -> bool:
        """Fill only the empty fields. Returns True when anything changed."""
        changed = False
        for attr in BIO_FIELDS:
            new = bio.get(attr)
            if new in (None, "") or getattr(player, attr, None) not in (None, ""):
                continue
            setattr(player, attr, new)
            changed = True
        return changed
