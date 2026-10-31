"""Graph nodes. Side effects go through tools (ToolClient: MCP or direct); decisions go through policy.decide().

Nodes that wait (collect_document, field_wait, human_review) call interrupt() first and do nothing before it:
LangGraph re-runs an interrupted node from the top on resume, so anything above interrupt() would run twice.
"""
import logging
from datetime import datetime
from typing import Optional

from langgraph.types import interrupt
from sqlmodel import Session

from .. import audit, clock, llm
from ..db import engine
from ..events import publish
from ..models import Employee, Journey, Merchant, Visit, utcnow
from ..tool_client import call_tool
from . import messages, policy
from .state import JourneyState, current_doc

log = logging.getLogger("qrwapsi.agent")


# ------------------------------------------------------------ helpers

def _merchant(mid: str) -> Merchant:
    with Session(engine) as s:
        m = s.get(Merchant, mid)
        if m is None:
            raise KeyError(f"merchant {mid} not found")
        return m


def _set_qr_status(mid: str, status: str) -> None:
    # LIVE is set only by tools.compliance.reactivate_qr, after the rules engine says compliant
    if status == "LIVE":
        raise ValueError("the agent never sets LIVE; reactivate_qr does, after rules_engine.evaluate()")
    with Session(engine) as s:
        m = s.get(Merchant, mid)
        if m.qr_status == status:
            return
        m.qr_status = status
        s.add(m)
        s.commit()
    publish("merchant.qr_status", mid, {"qr_status": status})


def _journey(mid: str, **fields) -> None:
    """Mirror progress onto the Journey row (what the dashboard lists) and tell the UI."""
    with Session(engine) as s:
        j = s.get(Journey, mid) or Journey(merchant_id=mid)
        for k, v in fields.items():
            setattr(j, k, v)
        j.updated_at = utcnow()
        s.add(j)
        s.commit()
        step = j.current_step
    publish("journey.updated", mid, {"current_step": step, **fields})


def _log(mid: str, action: str, payload: Optional[dict] = None) -> None:
    audit.log(mid, "agent", action, payload or {})


def _summary(state: JourneyState, **extra) -> dict:
    """What the LLM sees when proposing an action. No timestamps or ids, so demo-cache keys are stable."""
    return {"route": state.get("route"), "needed_docs": state.get("needed_docs", []),
            "accepted_docs": state.get("accepted_docs", []), "current_doc": current_doc(state),
            "doc_attempts": state.get("doc_attempts", {}), "channel_attempts": state.get("channel_attempts", {}), **extra}


def _decide(state: JourneyState, point: str, valid: list[str], default: str, why: str, **extra) -> str:
    # `situation` gives the LLM the same facts the policy used, so its reason matches the evidence
    return policy.decide(state["merchant_id"], point, _summary(state, situation=why, **extra), valid, default, why).final


def _whatsapp(m: Merchant, purpose: str, ctx: dict, attempts: dict) -> dict:
    msg = messages.compose(m, purpose, "WHATSAPP", ctx)
    call_tool("send_whatsapp", merchant_id=m.id, text_hi=msg["text_hi"], text_en=msg["text_en"])
    attempts["WHATSAPP"] = attempts.get("WHATSAPP", 0) + 1
    return {"channel": "WHATSAPP", "purpose": purpose, "source": msg["source"]}


def _soundbox(m: Merchant, purpose: str, attempts: dict, **ctx) -> dict:
    """Speak a fixed Hindi line on the shop's Soundbox (the tool attaches a cached Sarvam clip when one exists)."""
    res = call_tool("play_soundbox_prompt", merchant_id=m.id, text_hi=messages.soundbox_line(purpose, **ctx))
    attempts["SOUNDBOX"] = attempts.get("SOUNDBOX", 0) + 1
    return {"channel": "SOUNDBOX", "purpose": purpose, "source": "sarvam" if res.get("audio_ref") else "browser_voice"}


def _book_visit(mid: str) -> Optional[dict]:
    slot = call_tool("find_visit_slot", merchant_id=mid)
    if not slot["found"]:
        return None
    booking = call_tool("book_visit", merchant_id=mid, slot=slot["slot"])
    if not booking.get("ok"):
        return None
    _log(mid, "VISIT_SCHEDULED", {"slot": slot["slot"], "why": slot["reason"], "employee_id": booking["employee_id"],
                                  "route_order": booking["route_order"]})
    return booking


def _hhmm(iso: str) -> str:
    return datetime.fromisoformat(iso).strftime("%H:%M")


# ------------------------------------------------------------ nodes

def triage(state: JourneyState) -> dict:
    mid = state["merchant_id"]
    score = call_tool("score_merchant", merchant_id=mid)
    m = _merchant(mid)
    try:
        explanation, source = llm.explain_priority(m, score["reasons"]).summary_en, "llm"
    except Exception:  # noqa: BLE001
        explanation = "Ranked by " + "; ".join(f"{r['label'].lower()} ({r['detail']})" for r in score["reasons"]) + "."
        source = "policy"

    route = score["route"]
    esc = policy.triage_escalation(route, score["mule_risk"])
    needed: list[str] = []
    if not esc:
        if route == "CKYCR":
            if not call_tool("check_ckycr", merchant_id=mid)["found"]:
                needed = ["PAN", "OVD"]  # no record after all: collect documents (rules engine still decides)
        else:
            # A real DigiLocker hit would be stored as a document; the mock never returns one.
            needed = [d for d in ("PAN", "OVD")
                      if not call_tool("fetch_digilocker_document", merchant_id=mid, doc_type=d)["found"]]

    _journey(mid, current_step="TRIAGE", priority_score=score["priority_score"], priority_reasons=score["reasons"],
             mule_risk_score=score["mule_risk"]["score"])
    _set_qr_status(mid, "IN_PROGRESS")
    _log(mid, "TRIAGED", {"route": route, "priority_score": score["priority_score"], "reasons": score["reasons"],
                          "explanation": explanation, "explanation_source": source, "mule_risk": score["mule_risk"],
                          "needed_docs": needed, "escalation": esc})

    out: dict = {"route": route, "needed_docs": needed, "accepted_docs": [], "doc_attempts": {}, "channel_attempts": {},
                 "ladder_rung": 0, "request_kind": "FIRST", "escalation": None, "status": "ACTIVE"}
    if esc:
        out["escalation"] = {"reason": esc, "resume_to": "after_triage", "evidence": {
            "route": route, "mule_risk_score": score["mule_risk"]["score"],
            "top_risk_features": score["mule_risk"]["top_features"],
            "risk_features": m.risk_features, "monthly_gmv": m.monthly_gmv, "turnover_band": m.turnover_band}}
        valid, why = ["ESCALATE"], esc
    elif not needed:
        valid, why = ["SCHEDULE_VISIT"], "identity verified via CKYCR; only the in-person check remains"
    else:
        valid, why = ["REQUEST_DOCUMENT"], f"needs {', '.join(needed)}; no DigiLocker copy available"
    out["action"] = _decide({**state, **out}, "after_triage", valid, valid[0], why, priority_reasons=score["reasons"])
    return out


def request_document(state: JourneyState) -> dict:
    """Ask for the current document. FIRST and RETRY climb the contact ladder; replies to an engaged
    shopkeeper (FIX, NEXT, FORM60, REPLY_ACK, AFTER_REVIEW) go on WhatsApp."""
    mid = state["merchant_id"]
    m = _merchant(mid)
    kind = state.get("request_kind", "FIRST")
    doc = current_doc(state)
    rungs = policy.ladder(m.has_soundbox)
    rung = state.get("ladder_rung", 0)
    attempts = dict(state.get("channel_attempts", {}))
    ctx = {"doc_type": doc}
    sent: list[dict] = []
    visit_id = state.get("visit_id")

    if kind == "FIRST":
        rung = 0
        if rungs[0] == "SOUNDBOX":
            sent.append(_soundbox(m, "OUTREACH", attempts))
        sent.append(_whatsapp(m, "REQUEST_DOCUMENT", ctx, attempts))  # documents always come back on WhatsApp
    elif kind == "RETRY":
        rung = min(rung + 1, len(rungs) - 1)
        channel = rungs[rung]
        if channel == "WHATSAPP":
            sent.append(_whatsapp(m, "REMINDER", ctx, attempts))
        elif channel == "IVR":
            msg = messages.compose(m, "IVR_REQUEST", "IVR", ctx)
            call_tool("place_ivr_call", merchant_id=mid, text_hi=msg["text_hi"])
            attempts["IVR"] = attempts.get("IVR", 0) + 1
            sent.append({"channel": "IVR", "purpose": "IVR_REQUEST", "source": msg["source"]})
        elif channel == "FIELD_VISIT":
            booking = _book_visit(mid)
            if booking:
                visit_id = booking["visit_id"]
                attempts["FIELD_VISIT"] = attempts.get("FIELD_VISIT", 0) + 1
                sent.append(_whatsapp(m, "FIELD_COLLECT", {**ctx, "employee": booking["employee_name"],
                                                           "time": _hhmm(booking["scheduled_at"])}, attempts))
    else:
        rung = rungs.index("WHATSAPP")
        purpose = {"FIX": "DOCUMENT_REJECTED", "NEXT": "DOCUMENT_ACCEPTED_NEXT", "FORM60": "OFFER_FORM60",
                   "REPLY_ACK": "REPLY_ACK", "AFTER_REVIEW": "REQUEST_DOCUMENT"}[kind]
        check = state.get("last_check") or {}
        if kind == "FIX":
            ctx = {"doc_type": check["doc_type"], "fix_hi": check["fix_hi"], "fix_en": check["fix_en"]}
            if m.has_soundbox:
                sent.append(_soundbox(m, "DOCUMENT_FIX", attempts, fix_hi=check["fix_hi"]))
        elif kind == "NEXT":
            ctx["done_doc_type"] = check["doc_type"]
        sent.append(_whatsapp(m, purpose, ctx, attempts))

    _journey(mid, current_step="COLLECT", attempts=attempts)
    _log(mid, "DOCUMENT_REQUESTED", {"kind": kind, "doc_type": doc, "ladder_channel": rungs[rung], "sent": sent})
    return {"channel_attempts": attempts, "ladder_rung": rung, "last_contact_at": clock.now().isoformat(),
            "visit_id": visit_id}


def collect_document(state: JourneyState) -> dict:
    """Wait for the shopkeeper: an upload, a text reply, or a clock tick (no reply yet)."""
    event = interrupt({"waiting_for": "shopkeeper", "doc_type": current_doc(state)})

    mid = state["merchant_id"]
    etype = event.get("type")
    _log(mid, "EVENT_RECEIVED", {"waiting_for": "shopkeeper", **{k: event[k] for k in ("type", "doc_type", "text") if k in event}})
    out: dict = {"event": event}
    extra: dict = {"event": etype}
    doc = current_doc(state)

    if etype == "upload":
        valid, default, why = ["VERIFY_DOCUMENT"], "VERIFY_DOCUMENT", f"{event['doc_type']} photo received"
    elif etype == "reply":
        kind = policy.classify_reply(event.get("text", ""))
        extra["reply_kind"] = kind
        if kind == "DISPUTE":
            out["escalation"] = {"reason": "dispute raised by shopkeeper", "resume_to": "collect",
                                 "evidence": {"text": event.get("text", "")}}
            valid, default, why = ["ESCALATE"], "ESCALATE", "shopkeeper disputes the request"
        elif kind == "NO_PAN" and doc == "PAN":
            out["needed_docs"] = ["FORM60" if d == "PAN" else d for d in state["needed_docs"]]
            out["request_kind"] = "FORM60"
            valid, default, why = ["REQUEST_DOCUMENT"], "REQUEST_DOCUMENT", "shopkeeper has no PAN: offer Form 60"
        else:
            out["request_kind"] = "REPLY_ACK"
            valid, default, why = ["SEND_WHATSAPP", "WAIT"], "SEND_WHATSAPP", "reply without a document: restate what is needed"
    elif etype == "tick":
        hours = (clock.now() - datetime.fromisoformat(state["last_contact_at"])).total_seconds() / 3600
        rungs = policy.ladder(_merchant(mid).has_soundbox)
        valid, default, why = policy.tick_options(hours, state.get("ladder_rung", 0), len(rungs))
        out["request_kind"] = "RETRY"
        extra["hours_since_contact"] = round(hours, 1)
        extra["next_channel"] = rungs[min(state.get("ladder_rung", 0) + 1, len(rungs) - 1)]
    elif etype == "field_done":
        valid, default, why = ["WAIT"], "WAIT", "in-person check recorded; documents still awaited"
    else:
        valid, default, why = ["WAIT"], "WAIT", f"ignored event {etype}"

    out["action"] = _decide({**state, **out}, f"shopkeeper_{etype}", valid, default, why, **extra)
    return out


def verify_document(state: JourneyState) -> dict:
    mid = state["merchant_id"]
    ev = state["event"]
    doc_type = ev["doc_type"]
    attempts = dict(state.get("doc_attempts", {}))
    attempts[doc_type] = n = attempts.get(doc_type, 0) + 1
    _journey(mid, current_step="VERIFY")

    check = call_tool("check_document", merchant_id=mid, doc_type=doc_type, file_path=ev["file_path"], attempt_no=n)
    trimmed = {k: check[k] for k in ("document_id", "doc_type", "decision", "reason_code", "fix_en", "fix_hi",
                                     "confidence", "attempt_no", "extraction_source")}
    accepted = list(state.get("accepted_docs", []))
    out: dict = {"doc_attempts": attempts, "last_check": trimmed}

    if check["decision"] == "ACCEPTED":
        if doc_type not in accepted:
            accepted.append(doc_type)
        out["accepted_docs"] = accepted
        nxt = current_doc({**state, "accepted_docs": accepted})
        if nxt:
            out["request_kind"] = "NEXT"
            valid, why = ["REQUEST_DOCUMENT"], f"{doc_type} accepted; {nxt} still needed"
        else:
            valid, why = ["SCHEDULE_VISIT"], "all documents verified; the in-person check (CPV) is next"
    else:
        esc = policy.document_escalation(check, n)
        if esc:
            out["escalation"] = {"reason": esc, "resume_to": "request_document",
                                 "evidence": {k: check[k] for k in ("document_id", "doc_type", "reason_code", "confidence", "attempt_no")}}
            valid, why = ["ESCALATE"], esc
        else:
            out["request_kind"] = "FIX"
            valid, why = ["REQUEST_DOCUMENT"], f"{doc_type} rejected ({check['reason_code']}): send the specific fix"

    out["action"] = _decide({**state, **out}, "after_verify", valid, valid[0], why,
                            last_decision=check["decision"], reason_code=check["reason_code"])
    return out


def schedule_visit(state: JourneyState) -> dict:
    mid = state["merchant_id"]
    m = _merchant(mid)
    visit = None
    if state.get("visit_id"):
        with Session(engine) as s:
            visit = s.get(Visit, state["visit_id"])
    if visit is not None and visit.completed_at is not None:
        return {"action": _decide(state, "visit_already_done", ["RUN_COMPLIANCE"], "RUN_COMPLIANCE",
                                  "documents verified and the in-person check is already done")}

    if visit is None:
        booking = _book_visit(mid)
        if booking is None:
            return {"escalation": {"reason": "no visit slot inside the shop's open hours", "resume_to": "compliance",
                                   "evidence": {"open_hours": m.open_hours}}, "action": "ESCALATE"}
        visit_id, at, emp_id, emp_name = booking["visit_id"], booking["scheduled_at"], booking["employee_id"], booking["employee_name"]
    else:
        with Session(engine) as s:
            emp_name = s.get(Employee, visit.employee_id).name
        visit_id, at, emp_id = visit.id, visit.scheduled_at.isoformat(), visit.employee_id

    attempts = dict(state.get("channel_attempts", {}))
    _whatsapp(m, "CONFIRM_VISIT", {"employee": emp_name, "time": _hhmm(at)}, attempts)
    if m.has_soundbox:
        _soundbox(m, "VISIT_BOOKED", attempts, time=_hhmm(at))
    _journey(mid, current_step="FIELD_VISIT", visit_slot=datetime.fromisoformat(at), assigned_employee=emp_id, attempts=attempts)
    return {"visit_id": visit_id, "channel_attempts": attempts, "action": "WAIT_FIELD"}


def field_wait(state: JourneyState) -> dict:
    """Wait for the field employee. Only their completion of the visit moves the journey on (CPV is never skipped)."""
    event = interrupt({"waiting_for": "field_employee", "visit_id": state.get("visit_id")})

    mid = state["merchant_id"]
    _log(mid, "EVENT_RECEIVED", {"waiting_for": "field_employee", "type": event.get("type"), "visit_id": event.get("visit_id")})
    if event.get("type") != "field_done":
        return {"event": event, "action": "WAIT_FIELD"}
    action = _decide(state, "field_visit_done", ["RUN_COMPLIANCE"], "RUN_COMPLIANCE",
                     "in-person check recorded by the field employee", event="field_done")
    return {"event": event, "action": action}


def compliance(state: JourneyState) -> dict:
    mid = state["merchant_id"]
    _journey(mid, current_step="COMPLIANCE")
    res = call_tool("run_compliance", merchant_id=mid)
    failed = [r["requirement"] for r in res["results"] if not r["passed"]]
    out: dict = {"compliance": {"compliant": res["compliant"], "route": res["route"], "failed": failed}}
    if res["compliant"]:
        out["action"] = "REACTIVATE"
    elif failed == ["CPV_DONE"]:
        out["action"] = "WAIT_FIELD"  # the visit record is incomplete: wait for the field employee again
    else:
        reason = res["review_reason"] or "compliance check failed: " + ", ".join(failed)
        out["escalation"] = {"reason": reason, "resume_to": "compliance", "evidence": {"failed": failed}}
        out["action"] = "ESCALATE"
    _log(mid, "COMPLIANCE_RESULT", {**out["compliance"], "next": out["action"]})
    return out


def reactivate(state: JourneyState) -> dict:
    mid = state["merchant_id"]
    res = call_tool("reactivate_qr", merchant_id=mid)  # re-checks the rules engine itself
    if not res.get("ok"):
        return {"escalation": {"reason": "reactivation refused: " + ", ".join(res.get("failed", [])), "resume_to": "compliance",
                               "evidence": {"failed": res.get("failed", [])}}, "action": "ESCALATE"}
    m = _merchant(mid)
    _whatsapp(m, "QR_LIVE", {}, dict(state.get("channel_attempts", {})))
    _journey(mid, current_step="LIVE")
    _log(mid, "JOURNEY_COMPLETED", {"qr_status": "LIVE", "seal_hash": res["seal_hash"]})
    return {"status": "LIVE", "action": "DONE"}


def escalate(state: JourneyState) -> dict:
    mid = state["merchant_id"]
    esc = state["escalation"]
    case = call_tool("open_review_case", merchant_id=mid, reason=esc["reason"], evidence=esc.get("evidence") or {})
    _journey(mid, current_step="REVIEW", escalation_reason=esc["reason"])
    return {"review_case_id": case["case_id"]}


def human_review(state: JourneyState) -> dict:
    """Wait for a human decision on the ReviewCase. The agent never approves an escalated case itself."""
    event = interrupt({"waiting_for": "human_review", "case_id": state.get("review_case_id")})

    mid = state["merchant_id"]
    esc = state.get("escalation") or {}
    decision = event.get("decision")
    _log(mid, "EVENT_RECEIVED", {"waiting_for": "human_review", "type": event.get("type"), "decision": decision,
                                 "decided_by": event.get("decided_by"), "case_id": event.get("case_id")})
    if decision != "APPROVE" or state.get("route") == "FULL_CDD":
        return {"action": "CLOSE", "event": event}

    _set_qr_status(mid, "IN_PROGRESS")
    out: dict = {"escalation": None}
    resume_to = esc.get("resume_to")
    if resume_to == "after_triage":
        if current_doc(state):
            out["request_kind"] = "FIRST"
            valid, why = ["REQUEST_DOCUMENT"], "human cleared the risk flag: start collecting documents"
        else:
            valid, why = ["SCHEDULE_VISIT"], "human cleared the risk flag: book the in-person check"
    elif resume_to == "request_document":
        attempts = dict(state.get("doc_attempts", {}))
        attempts[(state.get("last_check") or {}).get("doc_type", "")] = 0
        out.update(doc_attempts=attempts, request_kind="AFTER_REVIEW")
        valid, why = ["REQUEST_DOCUMENT"], "human reviewed the document issue: ask for the document again"
    elif resume_to == "compliance":
        valid, why = ["RUN_COMPLIANCE"], "human reviewed: re-run the rules engine"
    else:
        valid, why = ["WAIT"], "human reviewed: keep waiting for the shopkeeper"
    out["action"] = _decide({**state, **out}, "after_review", valid, valid[0], why, review_decision=decision)
    return out


def closed(state: JourneyState) -> dict:
    mid = state["merchant_id"]
    _set_qr_status(mid, "PAUSED")
    _journey(mid, current_step="CLOSED")
    ev = state.get("event") or {}
    _log(mid, "JOURNEY_CLOSED", {"reason": (state.get("escalation") or {}).get("reason"), "decision": ev.get("decision"),
                                 "decided_by": ev.get("decided_by"), "note": ev.get("note")})
    return {"status": "CLOSED", "action": "DONE"}
