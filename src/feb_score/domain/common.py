from __future__ import annotations

from abc import ABC
from dataclasses import dataclass, field
from typing import Any, List


class DomainError(Exception):
    """Base class for domain-specific errors."""


@dataclass
class AggregateRoot(ABC):
    _domain_events: List[Any] = field(default_factory=list, init=False, repr=False)

    def _record_event(self, event: Any) -> None:
        self._domain_events.append(event)

    def collect_events(self) -> List[Any]:
        return list(self._domain_events)

    def clear_events(self) -> None:
        self._domain_events.clear()
