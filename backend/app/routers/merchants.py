from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from .. import audit, rules_engine
from ..db import get_session
from ..models import ChatMessage, Merchant

router = APIRouter()


def _merchant_or_404(merchant_id: str, session: Session) -> Merchant:
    m = session.get(Merchant, merchant_id)
    if m is None:
        raise HTTPException(404, f"merchant {merchant_id} not found")
    return m


@router.get("/{merchant_id}/audit")
def merchant_audit(merchant_id: str, session: Session = Depends(get_session)):
    _merchant_or_404(merchant_id, session)
    entries = audit.entries_for(merchant_id, session)
    return {
        "merchant_id": merchant_id,
        "chain": audit.verify_chain(merchant_id, session),
        "entries": [e.model_dump(mode="json") for e in entries],
    }


@router.get("/{merchant_id}/chat")
def merchant_chat(merchant_id: str, session: Session = Depends(get_session)):
    """WhatsApp and IVR history with the shopkeeper, oldest first (what the ShopSimulator shows)."""
    _merchant_or_404(merchant_id, session)
    rows = session.exec(select(ChatMessage).where(ChatMessage.merchant_id == merchant_id).order_by(ChatMessage.id))
    return {"merchant_id": merchant_id, "messages": [r.model_dump(mode="json") for r in rows]}


@router.get("/{merchant_id}/compliance")
def merchant_compliance(merchant_id: str, session: Session = Depends(get_session)):
    _merchant_or_404(merchant_id, session)
    return rules_engine.evaluate(merchant_id, session)
