from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

from ..common import AggregateRoot
from ..errors import InvalidPublication
from ..events import PublicationCreated
from ..value_objects import Actor, EventMeta, ExternalId, PublicationId, SnapshotId


@dataclass
class Publication(AggregateRoot):
    publication_id: PublicationId
    title: str
    content: str
    template_id: str
    references: List[Dict[str, str]] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.utcnow)
    created_by: Optional[Actor] = None
    published_at: Optional[datetime] = None
    status: str = field(default="DRAFT")
    locale: Optional[str] = None

    def create(self, creator: Actor, created_at: datetime, locale: Optional[str] = None) -> None:
        if not self.title:
            raise InvalidPublication("Publication must have a title")
        if not self.content:
            raise InvalidPublication("Publication must have content")
        self.created_by = creator
        self.created_at = created_at
        self.locale = locale
        self._record_event(
            PublicationCreated(
                event_id=str(self.publication_id.value),
                meta=EventMeta(version="1.0", produced_at=datetime.utcnow()),
                source={
                    "origin": "editor" if creator.role in {"admin", "editor"} else "system",
                    "actor": {"id": creator.id},
                },
                payload={
                    "publication_id": str(self.publication_id),
                    "status": self.status,
                    "references": self.references,
                },
            )
        )
