from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlmodel import Session, select

from .. import audit, llm, rules_engine
from ..config import BACKEND_DIR, settings
from ..db import get_session
from ..models import ChatMessage, Document, Journey, Merchant
from ..scoring import mule_risk, priority

router = APIRouter()

_explanations: dict[tuple, dict] = {}  # (merchant_id, reasons) -> explanation; the LLM is asked once per ranking


def _merchant_or_404(merchant_id: str, session: Session) -> Merchant:
    m = session.get(Merchant, merchant_id)
    if m is None:
        raise HTTPException(404, f"merchant {merchant_id} not found")
    return m


@router.get("/{merchant_id}")
def merchant_profile(merchant_id: str, session: Session = Depends(get_session)):
    m = _merchant_or_404(merchant_id, session)
    p = priority(m)
    j = session.get(Journey, merchant_id)
    return {
        **m.model_dump(mode="json", exclude={"hourly_txn_histogram"}),
        "priority_score": p.score, "reasons": p.reasons, "mule_risk": mule_risk(m.risk_features),
        "route": rules_engine.determine_route(m), "current_step": j.current_step if j else None,
    }


@router.get("/{merchant_id}/explanation")
def merchant_explanation(merchant_id: str, session: Session = Depends(get_session)):
    """One-line LLM explanation of the ranking (demo cache in replay), or a deterministic sentence if unavailable."""
    m = _merchant_or_404(merchant_id, session)
    reasons = priority(m).reasons
    key = (merchant_id, tuple((r["label"], r["detail"]) for r in reasons))
    if key not in _explanations:
        try:
            text, source = llm.explain_priority(m, reasons, write_audit=False).summary_en, "llm"
        except Exception:  # noqa: BLE001
            text = "Ranked by " + "; ".join(f"{r['label'].lower()} ({r['detail']})" for r in reasons) + "."
            source = "policy"
        _explanations[key] = {"merchant_id": merchant_id, "explanation": text, "source": source, "reasons": reasons}
    return _explanations[key]


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


def _serve_upload(file_path: str) -> FileResponse:
    path = Path(file_path).resolve()
    allowed = [(settings.DATA_DIR / "uploads").resolve(), (BACKEND_DIR / "demo_assets").resolve()]
    if not path.is_file() or not any(path.is_relative_to(a) for a in allowed):
        raise HTTPException(404, "image not available")
    return FileResponse(path)


@router.get("/{merchant_id}/chat/{message_id}/attachment")
def chat_attachment(merchant_id: str, message_id: int, session: Session = Depends(get_session)):
    msg = session.get(ChatMessage, message_id)
    if msg is None or msg.merchant_id != merchant_id or not msg.attachment:
        raise HTTPException(404, "attachment not found")
    return _serve_upload(msg.attachment)


@router.get("/{merchant_id}/documents")
def merchant_documents(merchant_id: str, session: Session = Depends(get_session)):
    """Every checked upload (and CKYCR record), newest first, with extracted fields and the decision."""
    _merchant_or_404(merchant_id, session)
    rows = session.exec(select(Document).where(Document.merchant_id == merchant_id).order_by(Document.id.desc()))
    return {"merchant_id": merchant_id, "documents": [
        {**d.model_dump(mode="json", exclude={"file_path"}),
         "image_url": f"/api/merchants/{merchant_id}/documents/{d.id}/image" if d.doc_type != "CKYCR" else None}
        for d in rows]}


@router.get("/{merchant_id}/documents/{doc_id}/image")
def document_image(merchant_id: str, doc_id: int, session: Session = Depends(get_session)):
    d = session.get(Document, doc_id)
    if d is None or d.merchant_id != merchant_id:
        raise HTTPException(404, "document not found")
    return _serve_upload(d.file_path)


@router.get("/{merchant_id}/compliance")
def merchant_compliance(merchant_id: str, session: Session = Depends(get_session)):
    """Read-only preview of the rules engine for screens (not audited; the agent's own evaluations are)."""
    _merchant_or_404(merchant_id, session)
    return rules_engine.evaluate(merchant_id, session, write_audit=False)
