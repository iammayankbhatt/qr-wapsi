from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel
from sqlmodel import Session, select

from .. import audit
from ..agent import service
from ..config import settings
from ..db import engine, get_session
from ..integrations.whatsapp import WhatsAppClient
from ..models import Journey, Merchant
from ..rules_engine import determine_route
from ..scoring import mule_risk, priority

router = APIRouter()

DOC_TYPES = ("PAN", "FORM60", "OVD")
MAX_UPLOAD_BYTES = 10 * 1024 * 1024


@router.get("/queue")
def queue(limit: int = Query(50, ge=1, le=1000), session: Session = Depends(get_session)):
    """Merchants still waiting for a live QR, highest priority first. Scored on the fly (days paused moves daily)."""
    rows = []
    for m in session.exec(select(Merchant).where(Merchant.qr_status != "LIVE")).all():
        p = priority(m)
        rows.append((p.score, m, p))
    rows.sort(key=lambda r: (-r[0], r[1].id))
    steps = {j.merchant_id: j.current_step for j in session.exec(select(Journey)).all()}
    items = [
        {
            "rank": i, "merchant_id": m.id, "shop_name": m.shop_name, "owner_name": m.owner_name,
            "category": m.category, "locality": m.locality, "city": m.city, "qr_status": m.qr_status,
            "route": determine_route(m), "current_step": steps.get(m.id),
            "monthly_gmv": m.monthly_gmv, "priority_score": p.score, "reasons": p.reasons,
            "mule_risk": mule_risk(m.risk_features),
        }
        for i, (_, m, p) in enumerate(rows[:limit], start=1)
    ]
    return {"total": len(rows), "limit": limit, "items": items}


# ------------------------------------------------------------ journeys

def _merchant_or_404(mid: str) -> Merchant:
    with Session(engine) as s:
        m = s.get(Merchant, mid)
    if m is None:
        raise HTTPException(404, f"merchant {mid} not found")
    return m


def journey_view(mid: str) -> dict:
    snap = service.snapshot(mid)
    with Session(engine) as s:
        m = s.get(Merchant, mid)
        j = s.get(Journey, mid)
        entries = audit.entries_for(mid, s)
        chain = audit.verify_chain(mid, s)
    values = snap["values"]
    return {
        "merchant_id": mid, "shop_name": m.shop_name, "qr_status": m.qr_status,
        "step": j.current_step if j else None, "started": snap["started"], "waiting_for": snap["waiting"],
        "visit_slot": j.visit_slot.isoformat() if j and j.visit_slot else None,
        "assigned_employee": j.assigned_employee if j else None,
        "attempts": j.attempts if j else {}, "escalation_reason": j.escalation_reason if j else None,
        "state": values, "chain": chain,
        "timeline": [{"id": e.id, "ts": e.ts.isoformat(), "actor": e.actor, "action": e.action,
                      "summary": e.payload.get("summary"), "payload": e.payload} for e in entries],
    }


def _resume(mid: str, event: dict, expect: str) -> dict:
    try:
        service.resume(mid, event, expect)
    except service.JourneyConflict as e:
        raise HTTPException(409, str(e)) from e
    return journey_view(mid)


@router.post("/journeys/{merchant_id}/start")
def start_journey(merchant_id: str):
    _merchant_or_404(merchant_id)
    service.start(merchant_id)
    return journey_view(merchant_id)


@router.get("/journeys/{merchant_id}")
def get_journey(merchant_id: str):
    _merchant_or_404(merchant_id)
    return journey_view(merchant_id)


@router.post("/journeys/{merchant_id}/upload")
def upload_document(merchant_id: str, file: UploadFile = File(...), doc_type: str = Form(...)):
    """The shopkeeper sends a photo of a document (from the ShopSimulator's WhatsApp chat)."""
    _merchant_or_404(merchant_id)
    doc_type = doc_type.upper()
    if doc_type not in DOC_TYPES:
        raise HTTPException(422, f"doc_type must be one of {DOC_TYPES}")
    data = file.file.read()
    if not data or len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(422, "file must be a non-empty image up to 10 MB")
    waiting = service.snapshot(merchant_id)["waiting"]
    if not waiting or waiting.get("waiting_for") != "shopkeeper":
        raise HTTPException(409, f"journey {merchant_id} is not waiting for a document")

    folder = settings.DATA_DIR / "uploads" / merchant_id
    folder.mkdir(parents=True, exist_ok=True)
    n = len(list(folder.glob("*"))) + 1
    path = folder / f"{n:02d}_{doc_type}{Path(file.filename or '').suffix.lower() or '.jpg'}"
    path.write_bytes(data)
    WhatsAppClient().receive(merchant_id, text=f"[{doc_type} photo]", attachment=str(path))
    return _resume(merchant_id, {"type": "upload", "doc_type": doc_type, "file_path": str(path)}, "shopkeeper")


class Reply(BaseModel):
    text: str


@router.post("/journeys/{merchant_id}/reply")
def shopkeeper_reply(merchant_id: str, body: Reply):
    """A text reply from the shopkeeper (e.g. "mere paas PAN nahi hai")."""
    _merchant_or_404(merchant_id)
    waiting = service.snapshot(merchant_id)["waiting"]
    if not waiting or waiting.get("waiting_for") != "shopkeeper":
        raise HTTPException(409, f"journey {merchant_id} is not waiting for the shopkeeper")
    WhatsAppClient().receive(merchant_id, text=body.text)
    return _resume(merchant_id, {"type": "reply", "text": body.text}, "shopkeeper")
