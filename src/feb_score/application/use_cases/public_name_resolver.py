"""Player + team names from the PUBLIC FEB match pages (``Partido.aspx``).

Unlike ``OfficialPlayerNameResolver`` (LiveStats + JWT) and the calendar team
resolver (limited to the single configured season), this reads names straight
from the public boxscore HTML that ``scripts/feb/parse_public_boxscore`` already
produces: works for ANY season, no token, no calendar season-gate. It fetches
the match pages concurrently so a full season resolves in seconds (no HTTP
timeout for the synchronous ``backfill_catalog`` command).

Deterministic name policy (identical to the calendar team resolver): the most
frequent name per external_id wins; ties break to the lexicographically
smallest name — stable across runs. Identity is always the external_id; names
are descriptive only and never select/merge entities.
"""
from __future__ import annotations

import os
import sys
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Dict, List, Optional, Tuple


def _import_ppb():
    """Late import of the sibling scraper (kept out of the app import graph)."""
    scripts_dir = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "scripts", "feb")
    )
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    import parse_public_boxscore as PPB  # noqa: E402

    return PPB


def _pick(names: List[str]) -> Optional[str]:
    counts = Counter(n for n in names if n)
    if not counts:
        return None
    top = max(counts.values())
    return sorted(n for n, c in counts.items() if c == top)[0]


class PublicBoxscoreNameResolver:
    """``CatalogNameResolver`` over the public match pages.

    ``kind`` is ``"players"`` or ``"teams"``. ``fetch``/``parse`` are injectable
    for tests; by default they use ``parse_public_boxscore``.
    """

    def __init__(
        self,
        match_repo,
        season_code: str,
        kind: str,
        *,
        max_workers: int = 6,
        fetch: Optional[Callable[[str], str]] = None,
        parse: Optional[Callable[[str, str], object]] = None,
    ) -> None:
        if kind not in ("players", "teams"):
            raise ValueError(f"kind must be 'players' or 'teams', not {kind!r}")
        self._match_repo = match_repo
        self._season = season_code
        self._kind = kind
        self._max_workers = max_workers
        ppb = _import_ppb() if (fetch is None or parse is None) else None
        self._fetch = fetch or (lambda mid: ppb.fetch_match_page(mid))
        self._parse = parse or (lambda html, mid: ppb.parse_public_boxscore(html, mid))

    def _pairs_for_match(self, match_id: str) -> List[Tuple[str, str]]:
        try:
            box = self._parse(self._fetch(match_id), match_id)
        except Exception:  # noqa: BLE001 — a single bad page never aborts the season
            return []
        pairs: List[Tuple[str, str]] = []
        if self._kind == "teams":
            for team in (box.home, box.away):
                if team.name:
                    pairs.append((str(team.external_id), team.name.strip()))
        else:
            for p in box.players:
                if p.name:
                    pairs.append((str(p.player_external_id), p.name.strip()))
        return pairs

    def resolve(self, season_code) -> Dict[str, Optional[str]]:
        match_ids = [str(m.external_id) for m in self._match_repo.search(str(season_code))]
        candidates: Dict[str, List[str]] = defaultdict(list)
        if match_ids:
            with ThreadPoolExecutor(max_workers=self._max_workers) as pool:
                for pairs in pool.map(self._pairs_for_match, match_ids):
                    for ext_id, name in pairs:
                        candidates[ext_id].append(name)
        return {ext_id: _pick(names) for ext_id, names in candidates.items()}
