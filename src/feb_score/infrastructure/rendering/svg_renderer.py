from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, Optional
from xml.sax.saxutils import escape

from ...application.content.interfaces import TemplateRenderer


PLACEHOLDER_RE = re.compile(r"\{\{\s*([a-zA-Z0-9_.\[\]]+)\s*(?::([^}]+))?\}\}")


class TemplateNotFound(Exception):
    pass


class SvgTemplateRenderer(TemplateRenderer):
    """Loads .svg templates and substitutes {{path.to.value}} placeholders.

    Path syntax:
        {{ headline }}                       — top-level key
        {{ facts.home_score }}               — nested key via dot
        {{ top_performers[0].points }}       — list index
        {{ highlights[0].label }}
        {{ missing.key : fallback text }}    — fallback when key missing/None

    Values are HTML/XML-escaped so user data cannot break the SVG.
    """

    def __init__(self, templates_dir: Path) -> None:
        self._dir = Path(templates_dir)

    def render(self, template_name: str, data: Dict[str, Any]) -> str:
        template = self._load(template_name)
        return self._substitute(template, data)

    def list_templates(self) -> list[str]:
        if not self._dir.is_dir():
            return []
        return sorted(p.stem for p in self._dir.glob("*.svg"))

    def _load(self, template_name: str) -> str:
        path = self._dir / f"{template_name}.svg"
        if not path.is_file():
            raise TemplateNotFound(f"template not found: {template_name}")
        return path.read_text(encoding="utf-8")

    def _substitute(self, template: str, data: Dict[str, Any]) -> str:
        def replace(match: re.Match[str]) -> str:
            path = match.group(1)
            fallback = match.group(2).strip() if match.group(2) else ""
            value = _resolve_path(data, path)
            if value is None or value == "":
                return escape(fallback)
            return escape(_format_value(value))

        return PLACEHOLDER_RE.sub(replace, template)


def _resolve_path(data: Any, path: str) -> Any:
    """Walk data by a dotted/indexed path. Returns None on any miss."""
    parts = _tokenize(path)
    current: Any = data
    for part in parts:
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


def _tokenize(path: str) -> list[Any]:
    tokens: list[Any] = []
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
    return tokens


def _format_value(value: Any) -> str:
    if isinstance(value, float):
        if value.is_integer():
            return str(int(value))
        return f"{value:.2f}"
    return str(value)
