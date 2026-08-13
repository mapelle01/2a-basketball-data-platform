from datetime import datetime
from uuid import uuid4

import pytest

from feb_score.domain.errors import InvalidPublication
from feb_score.domain.publication.model import Publication
from feb_score.domain.value_objects import Actor, ExternalId, PublicationId


def test_publication_creation_records_event():
    publication = Publication(
        publication_id=PublicationId(str(uuid4())),
        title="Match recap",
        content="A game summary",
        template_id="tpl-match-summary-v1",
        references=[{"type": "match", "id": "2513600"}],
    )
    publication.create(creator=Actor(id="editor-1", role="editor"), created_at=datetime.utcnow())
    events = publication.collect_events()
    assert len(events) == 1
    event = events[0]
    assert event.payload["publication_id"] == str(publication.publication_id)
    assert event.payload["status"] == publication.status
    assert event.payload["references"] == publication.references


def test_publication_requires_title_and_content():
    publication = Publication(
        publication_id=PublicationId(str(uuid4())),
        title="",
        content="",
        template_id="tpl-match-summary-v1",
    )
    with pytest.raises(InvalidPublication, match="title"):
        publication.create(creator=Actor(id="editor-1", role="editor"), created_at=datetime.utcnow())

    publication.title = "Valid title"
    with pytest.raises(InvalidPublication, match="content"):
        publication.create(creator=Actor(id="editor-1", role="editor"), created_at=datetime.utcnow())


def test_publication_references_must_be_type_id_objects():
    publication = Publication(
        publication_id=PublicationId(str(uuid4())),
        title="Reference test",
        content="Content",
        template_id="tpl-1",
        references=[{"type": "standing", "id": "snap-1"}],
    )
    publication.create(creator=Actor(id="editor-1", role="editor"), created_at=datetime.utcnow())
    events = publication.collect_events()
    assert events[0].payload["references"][0]["type"] == "standing"
