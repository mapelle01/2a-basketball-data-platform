"""The display-name standard: NOMBRE APELLIDOS.

FEB hands us the same person in two shapes, roughly half and half:

    "SAMAR, MATIJA"        surnames first, full given name
    "J. JUANOLA MADERA"    initial only — the given name is simply not there

so a feed mixes "STULIC, JOVAN" with "J. JUANOLA MADERA" and reads like two
different products. The house format is **given name first**, which is how a
Spanish reader says a name out loud.

Reordering is a formatting rule, not an invention: it moves what the source
already gave us. Expanding an initial WOULD be an invention, so a name that only
carries "J." is left exactly as it is — the fix for those is upstream, capturing
the fuller name from the player's profile, not guessing here.

Casing is deliberately preserved: the source is upper case and the templates
decide their own case, so this function never imposes one.
"""

from __future__ import annotations

import re
from typing import Optional

# "J." / "J.M." / "A. B." — an abbreviated given name we must not expand.
_INITIALS_RE = re.compile(r"^(?:[^\W\d_]\.\s*)+\S")


def is_abbreviated(name: Optional[str]) -> bool:
    """True when the given name is only an initial ("J. JUANOLA MADERA")."""
    return bool(name) and bool(_INITIALS_RE.match(name.strip()))


def display_name(name: Optional[str]) -> Optional[str]:
    """Render a source name as ``NOMBRE APELLIDOS``.

    ``"SAMAR, MATIJA"`` -> ``"MATIJA SAMAR"``. Anything without a comma is
    already in given-name-first order (or is an un-expandable initial form) and
    is returned untouched apart from whitespace. ``None``/blank stays falsy so
    callers keep their existing "fall back to the external id" behaviour.
    """
    if not name:
        return name
    cleaned = " ".join(name.split())
    if "," not in cleaned:
        return cleaned
    # Split on the FIRST comma only: "MAYS JR, MICHAEL LEE" keeps the suffix
    # with the surnames and the whole given name on the other side.
    surnames, _, given = cleaned.partition(",")
    surnames, given = surnames.strip(), given.strip()
    if not surnames or not given:
        return cleaned  # a stray comma is not a reorderable name
    return f"{given} {surnames}"


def prefer_fuller_name(current: Optional[str], candidate: Optional[str]) -> Optional[str]:
    """Pick the better of two source names for the same player.

    A name carrying the full given name beats one carrying only an initial, so
    the profile's "JUANOLA MADERA, JORDI" upgrades a boxscore's "J. JUANOLA
    MADERA". Anything else keeps ``current``: this is an upgrade rule, never a
    correction, so a name already as good is never churned.
    """
    if not candidate:
        return current
    if not current:
        return candidate
    if is_abbreviated(current) and not is_abbreviated(candidate):
        return candidate
    return current
