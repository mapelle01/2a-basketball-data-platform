#!/usr/bin/env python3
"""Remove the deploy smoke-test fixtures that accumulated in a real season.

WHY
---
Every production deploy runs ``scripts/staging_smoke.sh``, which proved the
write path by creating a match. It wrote that match into season 2025-2026,
round 1, under competition ``smoke-comp`` — and never removed it. One per
deploy, forever: 28 fake fixtures sitting inside a real season, inflating its
counts.

The smoke script now writes to a throwaway season (0000-0000), so no new ones
appear. This clears the ones already there.

SAFETY — this is the only destructive script in the repo, so it is narrow:
  * It matches ONLY rows whose competition_id is exactly 'smoke-comp' AND whose
    external_id starts with 'smoke-'. Both must hold.
  * It REFUSES to delete any match that has player or team stats attached — a
    real match can never be collateral, because a smoke fixture has none.
  * It prints what it would delete and stops. Deleting needs --confirm.
  * Domain events are left untouched: they are the audit trail of what
    happened, and what happened is that these matches were created.

USAGE
-----
    export FEB_SCORE_DATABASE_URL=postgres://…      # your production URL
    python scripts/maintenance/purge_smoke_matches.py            # dry run
    python scripts/maintenance/purge_smoke_matches.py --confirm  # delete
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import List, Tuple

SMOKE_COMPETITION = "smoke-comp"
SMOKE_PREFIX = "smoke-"

# Both conditions, always together: a prefix alone could match a real external
# id that happens to start with "smoke-", and a competition alone is one typo
# away from a real one.
_SELECT = """
    SELECT m.external_id, m.season_code, m.status
      FROM matches m
     WHERE m.competition_id = %s
       AND m.external_id LIKE %s
     ORDER BY m.external_id
"""

_HAS_STATS = """
    SELECT external_id FROM (
        SELECT match_external_id AS external_id FROM match_player_stats
        UNION
        SELECT match_external_id AS external_id FROM match_team_stats
    ) s
    WHERE s.external_id = ANY(%s)
"""

_DELETE = "DELETE FROM matches WHERE external_id = ANY(%s)"


def find_smoke(cur) -> List[Tuple[str, str, str]]:
    cur.execute(_SELECT, (SMOKE_COMPETITION, SMOKE_PREFIX + "%"))
    return [(r[0], r[1], r[2]) for r in cur.fetchall()]


def with_stats(cur, external_ids: List[str]) -> List[str]:
    """Any of these that carry stats — those are NOT smoke fixtures and must
    never be deleted, whatever their competition says."""
    if not external_ids:
        return []
    cur.execute(_HAS_STATS, (external_ids,))
    return [r[0] for r in cur.fetchall()]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--confirm", action="store_true",
                    help="actually delete (without this it is a dry run)")
    args = ap.parse_args(argv)

    url = os.environ.get("FEB_SCORE_DATABASE_URL", "").strip()
    if not url:
        raise SystemExit("CONFIG_ERROR: FEB_SCORE_DATABASE_URL is required")

    import psycopg

    with psycopg.connect(url) as conn:
        with conn.cursor() as cur:
            rows = find_smoke(cur)
            if not rows:
                print("No hay partidos de humo. Nada que limpiar.")
                return 0

            ids = [r[0] for r in rows]
            protected = with_stats(cur, ids)
            deletable = [i for i in ids if i not in set(protected)]

            seasons = sorted({r[1] for r in rows})
            print(f"Partidos de humo encontrados: {len(rows)}  ·  temporadas: {seasons}")
            for eid, season, status in rows[:5]:
                print(f"   {eid}  {season}  {status}")
            if len(rows) > 5:
                print(f"   … y {len(rows) - 5} más")

            if protected:
                print(f"\n⚠ {len(protected)} tienen estadísticas y NO se tocan: {protected}",
                      file=sys.stderr)

            if not args.confirm:
                print(f"\nENSAYO: se borrarían {len(deletable)}. "
                      f"Repite con --confirm para borrarlos de verdad.")
                return 0

            cur.execute(_DELETE, (deletable,))
            conn.commit()
            print(f"\nBorrados {cur.rowcount} partidos de humo.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
