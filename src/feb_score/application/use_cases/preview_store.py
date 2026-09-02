"""Ephemeral preview store — a card the operator has seen but not committed.

The Ideas dashboard's Fase B flow: click Generar → server renders + validates
the card and puts it here instead of the persistent queue, then hands the id
to the operator. The operator sees the image inline and picks Enviar a la cola
(promote to PENDING_REVIEW in the real queue) or Descartar (drop it here). A
card no one committed evaporates on TTL; the queue stays clean.

Kept as a plain in-memory dict:
* Process-local — a redeploy loses previews (fine; the operator refreshes and
  regenerates cheap).
* One TTL swept lazily on every access — no timer, no threads.
* Fresh cards evict the oldest when the map hits ``MAX_ITEMS`` — bounds memory
  even under a click frenzy.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Dict, Optional


DEFAULT_TTL_SECONDS = 30 * 60      # 30 minutes: long enough to iterate, short
                                   # enough that abandoned previews vanish.
MAX_ITEMS = 200                    # ceiling per process — well beyond any
                                   # realistic operator session.


@dataclass
class _Entry:
    item: Any                      # a ContentItem
    added_at: float


class PreviewStore:
    """Ephemeral cache of ContentItems held by content_id."""

    def __init__(
        self, ttl_seconds: int = DEFAULT_TTL_SECONDS, max_items: int = MAX_ITEMS,
    ) -> None:
        self._entries: Dict[str, _Entry] = {}
        self._ttl = ttl_seconds
        self._max = max_items

    def put(self, item: Any) -> None:
        self._sweep()
        # Bound the map: if we are already at the cap, drop the oldest.
        if len(self._entries) >= self._max:
            oldest_id = min(self._entries, key=lambda k: self._entries[k].added_at)
            self._entries.pop(oldest_id, None)
        self._entries[item.content_id] = _Entry(item=item, added_at=time.time())

    def get(self, content_id: str) -> Optional[Any]:
        self._sweep()
        entry = self._entries.get(content_id)
        return entry.item if entry is not None else None

    def pop(self, content_id: str) -> Optional[Any]:
        """Remove and return; used on commit (promote to the real queue) and
        on delete."""
        entry = self._entries.pop(content_id, None)
        return entry.item if entry is not None else None

    def has(self, content_id: str) -> bool:
        return self.get(content_id) is not None

    def _sweep(self) -> None:
        cutoff = time.time() - self._ttl
        stale = [k for k, e in self._entries.items() if e.added_at < cutoff]
        for k in stale:
            self._entries.pop(k, None)
