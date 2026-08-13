from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from functools import wraps
from pathlib import Path
from typing import Any, Callable, Dict, TypeVar

import jsonschema
from jsonschema import FormatChecker

CONTRACTS_ROOT = Path(__file__).resolve().parents[3] / "contracts"

_SCHEMA_CACHE: Dict[str, Dict[str, Any]] = {}

F = TypeVar("F", bound=Callable[..., Any])


class ContractValidationError(ValueError):
    """Raised when a command does not conform to its JSON Schema contract."""


def to_primitive(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if is_dataclass(value):
        return {k: to_primitive(v) for k, v in asdict(value).items()}
    if isinstance(value, dict):
        return {k: to_primitive(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_primitive(v) for v in value]
    return value


def load_schema(schema_path: str) -> Dict[str, Any]:
    if schema_path not in _SCHEMA_CACHE:
        _SCHEMA_CACHE[schema_path] = json.loads((CONTRACTS_ROOT / schema_path).read_text())
    return _SCHEMA_CACHE[schema_path]


def validate_command(command: Any, schema_path: str) -> None:
    """Validate a Command against its JSON Schema. Raises ContractValidationError on failure."""
    schema = load_schema(schema_path)
    try:
        jsonschema.validate(to_primitive(command), schema, format_checker=FormatChecker())
    except jsonschema.ValidationError as exc:
        raise ContractValidationError(str(exc.message)) from exc


def contract_validated(schema_path: str) -> Callable[[F], F]:
    """Decorator: validate a Command against a JSON Schema before the handler runs."""

    def decorator(method: F) -> F:
        @wraps(method)
        def wrapper(self: Any, command: Any, *args: Any, **kwargs: Any) -> Any:
            validate_command(command, schema_path)
            return method(self, command, *args, **kwargs)

        return wrapper  # type: ignore[return-value]

    return decorator