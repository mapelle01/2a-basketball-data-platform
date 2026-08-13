from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Optional

from ..common import AggregateRoot
from ..errors import InvalidCorrection, UnauthorizedCorrection
from ..events import CorrectionProposed, CorrectionApproved, CorrectionRejected
from ..value_objects import Actor, CorrectionProposalId, ExternalId, EventMeta, MatchId, role_meets


@dataclass
class CorrectionProposal(AggregateRoot):
    proposal_id: CorrectionProposalId
    match_external_id: ExternalId
    proposed_by: Actor
    proposed_at: datetime
    reason: str
    changes: list[Dict[str, object]]
    status: str = field(default="PROPOSED")
    approved_by: Optional[Actor] = None
    approved_at: Optional[datetime] = None
    previous_version: Optional[str] = None
    new_version: Optional[str] = None
    rejected_by: Optional[Actor] = None
    rejected_at: Optional[datetime] = None
    rejection_reason: Optional[str] = None
    comment: Optional[str] = None

    def ensure_can_be_approved_by(self, approver: Actor) -> None:
        if not role_meets(approver.role, "admin"):
            raise UnauthorizedCorrection("Only admin-level principals may approve corrections")
        if self.status != "PROPOSED":
            raise InvalidCorrection("Only proposed corrections may be approved")

    def approve(self, approver: Actor, approved_at: datetime, previous_version: str, new_version: str, comment: Optional[str] = None) -> None:
        self.ensure_can_be_approved_by(approver)

        self.status = "APPROVED"
        self.approved_by = approver
        self.approved_at = approved_at
        self.previous_version = previous_version
        self.new_version = new_version
        self.comment = comment

        self._record_event(
            CorrectionApproved(
                event_id=str(self.proposal_id.value),
                meta=EventMeta(version="1.0", produced_at=datetime.utcnow()),
                source={"origin": "admin", "actor": {"id": approver.id}},
                payload={
                    "proposal_id": str(self.proposal_id),
                    "applied_by": {"id": approver.id},
                    "applied_at": approved_at.isoformat(),
                    "affected_match_external_id": str(self.match_external_id),
                    "diff": {"changes": self.changes},
                    "previous_version": previous_version,
                    "new_version": new_version,
                },
            )
        )

    def reject(self, approver: Actor, rejected_at: datetime, reason: str) -> None:
        if not role_meets(approver.role, "admin"):
            raise UnauthorizedCorrection("Only admin-level principals may reject corrections")
        if self.status != "PROPOSED":
            raise InvalidCorrection("Only proposed corrections may be rejected")

        self.status = "REJECTED"
        self.rejected_by = approver
        self.rejected_at = rejected_at
        self.rejection_reason = reason
        self._record_event(
            CorrectionRejected(
                event_id=str(self.proposal_id.value),
                meta=EventMeta(version="1.0", produced_at=datetime.utcnow()),
                source={"origin": "admin", "actor": {"id": approver.id}},
                payload={
                    "proposal_id": str(self.proposal_id),
                    "rejected_by": approver.id,
                    "rejected_at": rejected_at.isoformat(),
                    "reason": reason,
                },
            )
        )
