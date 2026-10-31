"""Compliance, reactivation and human review. reactivate_qr re-runs the rules engine itself: no caller,
LLM or agent, can switch a QR back on unless rules_engine.evaluate() says compliant."""
from sqlmodel import Session, select

from .. import audit, rules_engine, voice
from ..db import engine
from ..events import publish
from ..integrations.soundbox import SoundboxClient
from ..models import Merchant, ReviewCase
from ..phrases import soundbox_line


def run_compliance(merchant_id: str) -> dict:
    """Deterministic rules-engine evaluation of every requirement on the merchant's route."""
    return rules_engine.evaluate(merchant_id)


def reactivate_qr(merchant_id: str) -> dict:
    """Seal the audit record and switch the QR to LIVE, only if the rules engine says compliant right now."""
    res = rules_engine.evaluate(merchant_id)
    if not res["compliant"]:
        failed = [r["requirement"] for r in res["results"] if not r["passed"]]
        audit.log(merchant_id, "rules_engine", "REACTIVATION_REFUSED", {"failed": failed, "review_reason": res["review_reason"]})
        return {"ok": False, "error": "not compliant", "failed": failed, "compliance": res}

    chain = audit.verify_chain(merchant_id)
    seal = audit.log(merchant_id, "rules_engine", "AUDIT_SEALED", {
        "route": res["route"], "chain_ok": chain["ok"], "entries_checked": chain["checked"],
        "results": [{k: r[k] for k in ("requirement", "passed", "evidence_ref")} for r in res["results"]],
    })
    with Session(engine) as s:
        m = s.get(Merchant, merchant_id)
        m.qr_status = "LIVE"
        s.add(m)
        s.commit()
    audit.log(merchant_id, "system", "QR_REACTIVATED", {"qr_status": "LIVE", "seal_hash": seal.hash})
    publish("merchant.qr_status", merchant_id, {"qr_status": "LIVE", "seal_hash": seal.hash})
    sb = SoundboxClient()
    sb.set_status(merchant_id, "LIVE")
    line = soundbox_line("QR_LIVE")
    sb.speak(merchant_id, line, voice.synthesize(line))
    return {"ok": True, "qr_status": "LIVE", "seal_hash": seal.hash, "chain_ok": chain["ok"], "compliance": res}


def open_review_case(merchant_id: str, reason: str, evidence: dict) -> dict:
    """Escalate to a human reviewer. The journey waits until a human decides; the agent never decides it."""
    with Session(engine) as s:
        case = s.exec(select(ReviewCase).where(ReviewCase.merchant_id == merchant_id, ReviewCase.status == "OPEN",
                                               ReviewCase.reason == reason)).first()
        new = case is None
        if new:
            case = ReviewCase(merchant_id=merchant_id, reason=reason, evidence=evidence)
            s.add(case)
        m = s.get(Merchant, merchant_id)
        m.qr_status = "ESCALATED"
        s.add(m)
        s.commit()
        s.refresh(case)
        case_id = case.id
    if new:
        audit.log(merchant_id, "agent", "ESCALATED", {"case_id": case_id, "reason": reason, "evidence": evidence})
        publish("review.opened", merchant_id, {"case_id": case_id, "reason": reason})
        publish("merchant.qr_status", merchant_id, {"qr_status": "ESCALATED"})
    return {"ok": True, "case_id": case_id, "reason": reason}
