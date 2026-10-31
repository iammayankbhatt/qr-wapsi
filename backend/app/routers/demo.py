from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from .. import clock
from ..agent import policy, service
from ..config import BACKEND_DIR
from ..db import engine
from ..events import publish
from ..models import Journey, Merchant
from ..scoring import MULE_REVIEW_THRESHOLD, mule_risk_score
from scripts.seed import reset_all

router = APIRouter()

ASSETS = BACKEND_DIR / "demo_assets"
# Specimen images the ShopSimulator and FieldApp offer instead of a camera (all fictional, watermarked).
SPECIMENS = {
    "pan_blurry.jpg": {"label": "PAN card (blurry photo)", "doc_type": "PAN", "use": "shop"},
    "pan_sharp.jpg": {"label": "PAN card (clear photo)", "doc_type": "PAN", "use": "shop"},
    "ovd_sharp.jpg": {"label": "ID document (clear photo)", "doc_type": "OVD", "use": "shop"},
    "signboard_sample.jpg": {"label": "Shop signboard", "doc_type": None, "use": "field"},
}


@router.post("/reset")
def reset():
    """Reseed merchants and clear audit log, review cases, documents, visits, chat, uploads and agent checkpoints;
    the simulated clock goes back to today 10:30."""
    counts = reset_all()
    now = clock.reset()
    publish("demo.reset", None, {"clock": now.isoformat()})
    return {"status": "ok", **counts, "clock": now.isoformat()}


@router.get("/clock")
def get_clock():
    return {"now": clock.now().isoformat()}


class Advance(BaseModel):
    hours: float = Field(2, gt=0, le=48)


@router.post("/advance-clock")
def advance_clock(body: Advance = Advance()):
    """The "+2 hours" button: move the simulated clock, then let every waiting journey run its retry ladder."""
    now = clock.advance(body.hours)
    publish("clock.advanced", None, {"now": now.isoformat(), "hours": body.hours})
    return {"now": now.isoformat(), "resumed": service.tick_all()}


class NoReply(BaseModel):
    merchant_id: str = "M0001"


@router.post("/no-reply")
def simulate_no_reply(body: NoReply = NoReply()):
    """The shopkeeper stays silent for the retry delay: the clock moves and only this journey climbs the ladder."""
    now = clock.advance(policy.RETRY_AFTER_H)
    publish("clock.advanced", None, {"now": now.isoformat(), "hours": policy.RETRY_AFTER_H})
    try:
        service.resume(body.merchant_id, {"type": "tick"}, "shopkeeper")
    except service.JourneyConflict as e:
        raise HTTPException(409, f"{e}. Start the journey first, or it is no longer waiting on the shopkeeper.") from e
    with Session(engine) as s:
        j = s.get(Journey, body.merchant_id)
        attempts = j.attempts
    return {"now": now.isoformat(), "merchant_id": body.merchant_id, "attempts": attempts}


@router.post("/risky")
def trigger_risky_merchant():
    """Start the journey of a not-yet-started merchant with a high mule-risk score: it escalates to human review."""
    with Session(engine) as s:
        started = {j.merchant_id for j in s.exec(select(Journey).where(Journey.current_step != "TRIAGE"))}
        mid = next((m.id for m in s.exec(select(Merchant).where(Merchant.turnover_band != "ABOVE_40L").order_by(Merchant.id))
                    if m.id not in started and m.qr_status == "PAUSED"
                    and mule_risk_score(m.risk_features) >= MULE_REVIEW_THRESHOLD), None)
    if mid is None:
        raise HTTPException(409, "no unstarted high-risk merchant left; reset the demo")
    snap = service.start(mid)
    with Session(engine) as s:
        m = s.get(Merchant, mid)
        return {"merchant_id": mid, "shop_name": m.shop_name, "qr_status": m.qr_status,
                "waiting_for": snap["waiting"], "reason": s.get(Journey, mid).escalation_reason}


@router.get("/specimens")
def specimens():
    return {"specimens": [{"name": n, **meta, "url": f"/api/demo/specimens/{n}"}
                          for n, meta in SPECIMENS.items() if (ASSETS / n).exists()]}


@router.get("/specimens/{name}")
def specimen_file(name: str):
    if name not in SPECIMENS or not (ASSETS / name).exists():
        raise HTTPException(404, "unknown specimen")
    return FileResponse(ASSETS / name, media_type="image/jpeg")
