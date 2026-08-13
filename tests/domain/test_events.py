from datetime import datetime
from uuid import uuid4

from feb_score.domain.events import MatchUpserted
from feb_score.domain.value_objects import EventMeta


def test_domain_event_to_dict():
    event = MatchUpserted(
        event_id=str(uuid4()),
        meta=EventMeta(version="1.0", produced_at=datetime.utcnow()),
        source={"origin": "system", "actor": {"id": "system-1"}},
        payload={"external_id": "2513600", "status": "SCHEDULED"},
    )

    payload = event.to_dict()
    assert payload["event_id"] == event.event_id
    assert payload["payload"]["external_id"] == "2513600"
