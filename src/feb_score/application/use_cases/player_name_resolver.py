#!/usr/bin/env python3
"""FASE 24.2 — Official player name resolver.

Builds the canonical ``player_external_id -> official_name`` map by reading the
real FEB BoxScore payloads that the ingestion pipeline already uses.

Why this source (not the DB):
    * ``ingest_match.py`` parses the BoxScore JSON
      (HEADER.TEAM[] / BOXSCORE.TEAM[].PLAYER[] -> id, name) and discards the
      player names — they are intentionally absent from the ``players`` catalog
      and from ``match_player_stats`` (the API contract payload is restrictive).
    * The names survive only inside the FEB BoxScore endpoint
      (``intrafeb.feb.es/LiveStats.API/api/v1/BoxScore/{match_id}``), the SAME
      source ``scripts/feb/ingest_match.py`` already fetches with ``FEB_TOKEN``.

Re-uses the existing ingestion primitives (``fetch_feb_boxscore`` +
``parse_boxscore``) from ``scripts/feb/ingest_match.py`` — no new scraping,
no new architecture, no new FEB surface area.

Identity rule (unchanged): player identity = the FEB ``id`` returned by the
BoxScore, which IS the ``player_external_id`` already stored in
``match_player_stats`` (verified: e.g. production ``2772828``). Names are
descriptive attributes only — they never select/replace an identity.

Security:
    * ``FEB_TOKEN`` is read from env and passed straight to the FEB client; it
      is never logged, never stored, never serialized, never surfaced in
      exceptions (the FEB client masks headers itself).
    * Absent token: fails CLOSED with ``SourceError`` (never invents names).
"""
from __future__ import annotations

import json
import os
import sys
from typing import Callable, Dict, Optional


def _env(name: str, default: Optional[str] = None) -> Optional[str]:
    v = os.environ.get(name, "").strip()
    return v or default


def _import_feb():
    """Late import: keeps the application layer free of script-level coupling
    so this resolver is testable without ``scripts/`` on sys.path at import."""
    scripts_dir = os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "scripts", "feb")
    repo_root = os.path.abspath(os.path.join(scripts_dir, "..", ".."))
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)  # noqa: S324 (local, deterministic)
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)
    import discover_matches  # noqa: F401  (imported for side-effect / sibling resolution)
    import ingest_match  # noqa: E402
    return ingest_match


class SourceError(RuntimeError):
    """Controlled failure of the official name source (no secret in message)."""


class CatalogNameResolver:
    """Protocol mirror from catalog_backfill_service (kept self-contained)."""

    def resolve(self, season_code) -> Dict[str, Optional[str]]:
        raise NotImplementedError


class OfficialPlayerNameResolver(CatalogNameResolver):
    """Resolve ``player_external_id -> official_name`` from the real FEB
    BoxScore (the same payload the ingestion pipeline fetches).

    ``boxscore_loader`` is injectable for offline tests and accepts a FEB
    ``match_id`` + ``token`` and returns the parsed dict (with
    ``BOXSCORE.TEAM[].PLAYER[].id/.name``). The default loader is the live FEB
    endpoint used by ``ingest_match.fetch_feb_boxscore`` + ``parse_boxscore``.
    """

    def __init__(
        self,
        match_repo,
        stats_repo,
        season_code: str,
        *,
        token: Optional[str] = None,
        boxscore_loader: Optional[Callable[[str, str], dict]] = None,
        max_matches: Optional[int] = None,
    ) -> None:
        self._match_repo = match_repo
        self._stats_repo = stats_repo
        self._season = season_code
        self._token = token or _env("FEB_TOKEN")
        self._boxscore_loader = boxscore_loader
        self._max_matches = max_matches
        # diagnostic counters populated by resolve() (never secrets)
        self._resolved = 0
        self._unresolved = 0
        self._conflicts = 0

    def resolve(self, season_code) -> Dict[str, Optional[str]]:
        # target set = distinct player_external_id with stats this season
        aggregates = self._stats_repo.list_season_player_aggregates(season_code)
        targets = sorted({a.player_external_id for a in aggregates})
        if not targets:
            return {}

        if not self._token and self._boxscore_loader is None:
            # fail closed: without a token we cannot reach the official source;
            # record the diagnostic so callers can report unresolved without a raise
            self._resolved = 0
            self._unresolved = len(targets)
            raise SourceError(
                "FEB_TOKEN is not available; official player names cannot be "
                "resolved (set FEB_TOKEN or inject a boxscore_loader)"
            )

        loader = self._boxscore_loader or self._live_loader()
        match_ids = [str(m.external_id) for m in self._match_repo.search(season_code)]
        if self._max_matches is not None:
            match_ids = match_ids[: self._max_matches]

        names: Dict[str, Optional[str]] = {}
        seen_targets = set()
        for match_id in match_ids:
            if seen_targets >= set(targets):
                break
            try:
                parsed = loader(match_id, self._token or "")
            except SourceError:  # noqa: BLE001 - controlled source error
                raise
            except Exception as exc:  # noqa: BLE001 - per-match isolation
                # one un-fetchable boxscore doesn't abort the whole resolution
                print(f"FASE 24.2 WARN boxscore {match_id} unavailable: type={type(exc).__name__}",
                      file=sys.stderr)
                continue
            for pid, name in self._extract_names(parsed).items():
                names[pid] = name
                if pid in targets:
                    seen_targets.add(pid)

        # every target must be present in the result (None when unresolved)
        for pid in targets:
            names.setdefault(pid, None)

        # diagnostic counts (conflicts are surfaced later by the backfill service
        # as warnings when an existing name != official name)
        self._resolved = sum(1 for v in names.values() if v)
        self._unresolved = sum(1 for v in names.values() if not v)
        return names

    def last_stats(self) -> tuple:
        """(resolved, unresolved, conflicts) from the last ``resolve()`` call.

        ``conflicts`` is populated by the backfill service (it detects
        existing-name != official-name); this resolver only reports the
        source-level resolved/unresolved counts.
        """
        return (self._resolved, self._unresolved, self._conflicts)

    def _live_loader(self) -> Callable[[str, str], dict]:
        ingest = _import_feb()

        def _load(match_id: str, token: str) -> dict:
            box = ingest.fetch_feb_boxscore(match_id, token)
            return ingest.parse_boxscore(box, match_id=match_id, season_code=self._season)
        return _load

    @staticmethod
    def _extract_names(parsed: dict) -> Dict[str, str]:
        """``BOXSCORE.TEAM[].PLAYER.id/name`` -> {external_id: name}.

        The same ids are emitted by ``parse_boxscore`` as
        ``stats.home``/``stats.away`` player entries (``id`` + ``name``).
        """
        out: Dict[str, str] = {}
        def _take(players):
            for p in players or []:
                pid = p.get("id")
                name = p.get("name")
                if pid is not None and name:
                    out[str(pid)] = name
        bs = (parsed.get("BOXSCORE") or {}).get("TEAM") or []
        if bs:
            for team in bs:
                _take(team.get("PLAYER") or [])
        else:
            # parse_boxscore also surfaces them under parsed["stats"]
            for side in ("home", "away"):
                stats_home = (parsed.get("stats") or {}).get(side) or []
                for p in stats_home:
                    pid = p.get("id")
                    name = p.get("name")
                    if pid is not None and name:
                        out[str(pid)] = name
        return out
