"""Human review queue. Only a person decides an escalated case; the agent waits for that decision."""
from typing import Literal, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from .. import audit
from ..agent import service
from ..db import engine
from ..events import publish
from ..models import Merchant, ReviewCase
from .journeys import journey_view

router = APIRouter()


@router.get("")
def list_cases(status: Optional[str] = "OPEN"):
    with Session(engine) as s:
        q = select(ReviewCase).order_by(ReviewCase.id)
        if status:
            q = q.where(ReviewCase.status == status)
        cases = []
        for c in s.exec(q):
            m = s.get(Merchant, c.merchant_id)
            cases.append({**c.model_dump(mode="json"), "shop_name": m.shop_name if m else None})
    return {"cases": cases}


class Decide(BaseModel):
    decided_by: str = Field(min_length=1)  # reviewer's name; stored as "human:<name>"
    decision: Literal["APPROVE", "REJECT"]
    note: Optional[str] = None


@router.post("/{case_id}/decide")
def decide_case(case_id: int, body: Decide):
    actor = f"human:{body.decided_by.strip()}"
    with Session(engine) as s:
        c = s.get(ReviewCase, case_id)
        if c is None:
            raise HTTPException(404, f"review case {case_id} not found")
        if c.status != "OPEN":
            raise HTTPException(409, f"review case {case_id} is already decided")
        c.status, c.decided_by, c.decision, c.note = "DECIDED", actor, body.decision, body.note
        s.add(c)
        s.commit()
        mid = c.merchant_id

    audit.log(mid, actor, "REVIEW_DECIDED", {"case_id": case_id, "decision": body.decision, "note": body.note})
    publish("review.decided", mid, {"case_id": case_id, "decision": body.decision, "decided_by": actor})
    try:
        service.resume(mid, {"type": "review_decided", "case_id": case_id, "decision": body.decision,
                             "decided_by": actor}, "human_review")
    except service.JourneyConflict:
        pass  # case opened outside a journey: the decision is recorded, nothing to resume
    return journey_view(mid)
