from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session, select

from .. import audit
from ..db import get_session
from ..models import AuditEntry, Merchant

router = APIRouter()


@router.get("/verify")
def verify(merchant_id: Optional[str] = None, session: Session = Depends(get_session)):
    """Verify one merchant's hash chain, or all chains when merchant_id is omitted."""
    return audit.verify_chain(merchant_id, session)


@router.get("/recent")
def recent(limit: int = Query(40, ge=1, le=200), session: Session = Depends(get_session)):
    """Newest audit entries across all merchants (the dashboard's live activity feed)."""
    rows = session.exec(select(AuditEntry).order_by(AuditEntry.id.desc()).limit(limit)).all()
    names = {m.id: m.shop_name for m in session.exec(select(Merchant).where(Merchant.id.in_({r.merchant_id for r in rows})))}
    return {"entries": [{"id": e.id, "ts": e.ts.isoformat(), "merchant_id": e.merchant_id, "shop_name": names.get(e.merchant_id),
                         "actor": e.actor, "action": e.action, "summary": e.payload.get("summary"), "payload": e.payload}
                        for e in rows]}
