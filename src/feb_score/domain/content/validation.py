"""Fact Validator + Visual Validator — the two guards before publication.

Fact Validator
--------------
Extracts numeric claims from the generated copy. Every number must appear
in the Story's ``facts`` payload; every entity name must appear as a facts
value. A copy claim not found in the facts list is a hallucination — FAIL.

Visual Validator
----------------
v1 checks:
  - all required slots for the template are present
  - rendered SVG parses as XML
  - no ``{{ placeholder }}`` left un-substituted

Full-fidelity visual QA (contrast, text overflow, safe area) requires image
rasterization; deferred to v2 with the Level A/B asset work.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Sequence, Set, Tuple


# A "free-standing" number: a numeric literal NOT embedded in a word. Numbers
# glued to letters (a player alias like "p1", a team name like "76ers") are part
# of an entity name, not a statistical claim, so they must not be extracted.
# Hyphens in copy (e.g. "104-72") are score separators, not negative signs, so
# a leading digit is the only left-guard. Deterministic v1 copy never emits
# negative numbers; an LLM-based generator can extend this later.
_LETTER = r"A-Za-zÀ-ÖØ-öø-ÿ"
_NUMBER_RE = re.compile(rf"(?<![{_LETTER}\d])\d+(?:[.,]\d+)?(?![{_LETTER}])")
_LEFTOVER_PLACEHOLDER_RE = re.compile(r"\{\{\s*[a-zA-Z0-9_.\[\]]+\s*(?::[^}]*)?\}\}")


# ---------------------------------------------------------------------------
# Fact Validator
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FactValidationResult:
    ok: bool
    hallucinated_numbers: Tuple[str, ...]
    unknown_entities: Tuple[str, ...]
    detail: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "hallucinated_numbers": list(self.hallucinated_numbers),
            "unknown_entities": list(self.unknown_entities),
            "detail": self.detail,
        }


def validate_copy(copy_dict: Dict[str, Any], story_facts: Dict[str, Any]) -> FactValidationResult:
    """Compare every number in the copy to the source facts.

    v1 policy — NUMBERS ONLY. Deterministic copy generation cannot invent
    entity names (every name comes from a ``facts.get(...)`` call), so entity
    checking is deferred to the LLM-based generator planned for v2.
    """
    strings = [copy_dict.get(k, "") for k in ("headline", "subtitle", "caption")]
    combined = " ".join(s for s in strings if isinstance(s, str))

    allowed_numbers = _extract_allowed_numbers(story_facts)
    numbers_in_copy = set(_NUMBER_RE.findall(combined))
    hallucinated = tuple(sorted(n for n in numbers_in_copy if _normalize(n) not in allowed_numbers))

    ok = not hallucinated
    detail = f"hallucinated numbers: {list(hallucinated)}" if hallucinated else ""

    return FactValidationResult(
        ok=ok,
        hallucinated_numbers=hallucinated,
        unknown_entities=(),
        detail=detail,
    )


def _extract_allowed_numbers(facts: Dict[str, Any]) -> Set[str]:
    allowed: Set[str] = set()

    def walk(obj: Any) -> None:
        if isinstance(obj, dict):
            for v in obj.values():
                walk(v)
        elif isinstance(obj, (list, tuple)):
            for v in obj:
                walk(v)
        elif isinstance(obj, bool):
            return
        elif isinstance(obj, (int, float)):
            allowed.add(_normalize(str(obj)))
        elif isinstance(obj, str) and obj.isdigit():
            # A purely-numeric external_id (e.g. "2772828", "979897") is a real,
            # traceable value. When a display name is missing and the copy falls
            # back to the external_id, that number is NOT a hallucination.
            allowed.add(_normalize(obj))

    walk(facts)
    return allowed


def _normalize(number_string: str) -> str:
    """Normalize numeric literal so `2.0` and `2` match."""
    s = number_string.replace(",", ".")
    try:
        f = float(s)
        if f.is_integer():
            return str(int(f))
        return f"{f:g}"
    except ValueError:
        return s


# ---------------------------------------------------------------------------
# Visual Validator
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class VisualValidationResult:
    ok: bool
    missing_slots: Tuple[str, ...]
    unsubstituted_placeholders: Tuple[str, ...]
    parse_error: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "missing_slots": list(self.missing_slots),
            "unsubstituted_placeholders": list(self.unsubstituted_placeholders),
            "parse_error": self.parse_error,
        }


def validate_visual(
    rendered_svg: str,
    required_slots: Sequence[str],
    provided_data: Dict[str, Any],
) -> VisualValidationResult:
    """Check required slots are provided and no placeholders remain."""
    missing = tuple(sorted(s for s in required_slots if _resolve(provided_data, s) in (None, "", [])))

    leftover = tuple(sorted(set(_LEFTOVER_PLACEHOLDER_RE.findall(rendered_svg))))

    parse_error = ""
    try:
        import xml.etree.ElementTree as ET
        ET.fromstring(rendered_svg)
    except Exception as exc:  # noqa: BLE001 - report any XML issue
        parse_error = f"{type(exc).__name__}: {exc}"

    ok = not missing and not leftover and not parse_error
    return VisualValidationResult(
        ok=ok,
        missing_slots=missing,
        unsubstituted_placeholders=leftover,
        parse_error=parse_error,
    )


def _resolve(data: Any, path: str) -> Any:
    """Walk data by dotted/indexed path — mirrors svg_renderer._resolve_path."""
    tokens: List[Any] = []
    for segment in path.split("."):
        while segment:
            bracket = segment.find("[")
            if bracket == -1:
                tokens.append(segment)
                break
            if bracket > 0:
                tokens.append(segment[:bracket])
            end = segment.find("]", bracket)
            if end == -1:
                tokens.append(segment[bracket:])
                break
            tokens.append(int(segment[bracket + 1 : end]))
            segment = segment[end + 1 :]

    current: Any = data
    for part in tokens:
        if current is None:
            return None
        if isinstance(part, int):
            if not isinstance(current, (list, tuple)) or part >= len(current):
                return None
            current = current[part]
        else:
            if not isinstance(current, dict) or part not in current:
                return None
            current = current[part]
    return current
