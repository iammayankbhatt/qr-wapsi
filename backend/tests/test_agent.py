"""Agent behaviour from CLAUDE.md: decide (LLM proposes, policy accepts/overrides), recover, retry, escalate, state."""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app import llm
from app.agent import policy, service
from app.db import engine
from app.llm import LLMUnavailable, NextAction
from app.main import app
from app.models import Merchant
from app.rules_engine import evaluate
from app.scoring import MULE_REVIEW_THRESHOLD, mule_risk_score
from app.tools import reactivate_qr
from tests.conftest import make_merchant

ASSETS = Path(__file__).resolve().parent.parent / "demo_assets"
HERO = "M0001"


@pytest.fixture
def client():
    with TestClient(app) as c:
        assert c.post("/api/demo/reset").status_code == 200
        yield c
        c.post("/api/demo/reset")  # leave seeded data as other tests expect it


def upload(c, mid, name, doc_type):
    with open(ASSETS / name, "rb") as f:
        r = c.post(f"/api/journeys/{mid}/upload", files={"file": (name, f, "image/jpeg")}, data={"doc_type": doc_type})
    assert r.status_code == 200, r.text
    return r.json()


def decisions(view):
    return [e["payload"] for e in view["timeline"] if e["action"] == "DECISION"]


def first_merchant(where):
    with Session(engine) as s:
        return next(m.id for m in s.exec(select(Merchant).order_by(Merchant.id)) if where(m))


# ------------------------------------------------------------ decide

def test_llm_proposal_is_accepted_and_both_are_audited(client, monkeypatch):
    seen = []

    def propose(summary, allowed, **kw):
        seen.append(list(allowed))
        return NextAction(action=allowed[0], reason="clear next step", confidence=0.86)

    monkeypatch.setattr(llm, "propose_next_action", propose)
    v = client.post(f"/api/journeys/{HERO}/start").json()
    d = decisions(v)[0]
    assert seen[0] == ["REQUEST_DOCUMENT"]  # only the actions valid for the state are offered
    assert d["verdict"] == "accepted" and d["final"] == "REQUEST_DOCUMENT"
    assert d["summary"] == "LLM proposed REQUEST_DOCUMENT (conf 0.86) → policy accepted"


def test_low_confidence_proposal_is_overridden(client, monkeypatch):
    monkeypatch.setattr(llm, "propose_next_action",
                        lambda s, a, **kw: NextAction(action=a[-1], reason="unsure", confidence=0.3))
    client.post(f"/api/journeys/{HERO}/start")
    client.post("/api/demo/advance-clock", json={"hours": 2})  # valid: REQUEST_DOCUMENT, WAIT; LLM says WAIT at 0.3
    d = decisions(client.get(f"/api/journeys/{HERO}").json())[-1]
    assert d["valid"] == ["REQUEST_DOCUMENT", "WAIT"] and d["proposed"] == "WAIT"
    assert d["verdict"] == "overrode" and d["final"] == "REQUEST_DOCUMENT"


def test_confident_wait_is_accepted_but_the_policy_forces_a_retry_later(client, monkeypatch):
    monkeypatch.setattr(llm, "propose_next_action",
                        lambda s, a, **kw: NextAction(action="WAIT" if "WAIT" in a else a[0], reason="give them time", confidence=0.9))
    client.post(f"/api/journeys/{HERO}/start")
    v = client.post("/api/demo/advance-clock", json={"hours": 2}).json()
    assert v["resumed"] == [HERO]
    j = client.get(f"/api/journeys/{HERO}").json()
    assert decisions(j)[-1]["final"] == "WAIT" and j["attempts"] == {"SOUNDBOX": 1, "WHATSAPP": 1}
    client.post("/api/demo/advance-clock", json={"hours": 2})  # 4 h without a reply: WAIT is no longer valid
    j = client.get(f"/api/journeys/{HERO}").json()
    assert decisions(j)[-1]["valid"] == ["REQUEST_DOCUMENT"] and j["attempts"]["WHATSAPP"] == 2


def test_journey_never_gets_stuck_when_the_llm_is_down(client, monkeypatch):
    def down(*a, **kw):
        raise LLMUnavailable("simulated outage")

    for name in ("propose_next_action", "draft_message", "explain_priority", "extract_document"):
        monkeypatch.setattr(llm, name, down)
    client.post(f"/api/journeys/{HERO}/start")
    upload(client, HERO, "pan_sharp.jpg", "PAN")  # extraction falls back to the specimen manifest
    v = upload(client, HERO, "ovd_sharp.jpg", "OVD")
    assert v["state"]["last_check"]["extraction_source"] == "specimen_manifest"
    assert v["waiting_for"]["waiting_for"] == "field_employee"
    assert all(d["verdict"] == "decided_alone" for d in decisions(v))
    assert "नमस्ते" in client.get(f"/api/merchants/{HERO}/chat").json()["messages"][0]["text_hi"]  # template message


# ------------------------------------------------------------ recover and retry

def test_retry_ladder_soundbox_whatsapp_ivr_field_visit(client):
    client.post(f"/api/journeys/{HERO}/start")
    assert client.post("/api/demo/advance-clock", json={"hours": 1}).json()["resumed"] == [HERO]
    assert client.get(f"/api/journeys/{HERO}").json()["attempts"] == {"SOUNDBOX": 1, "WHATSAPP": 1}  # too soon
    client.post("/api/demo/advance-clock", json={"hours": 1})
    assert client.get(f"/api/journeys/{HERO}").json()["attempts"] == {"SOUNDBOX": 1, "WHATSAPP": 2}
    client.post("/api/demo/advance-clock", json={"hours": 2})
    j = client.get(f"/api/journeys/{HERO}").json()
    assert j["attempts"]["IVR"] == 1
    assert client.get(f"/api/merchants/{HERO}/chat").json()["messages"][-1]["channel"] == "IVR"
    client.post("/api/demo/advance-clock", json={"hours": 2})
    j = client.get(f"/api/journeys/{HERO}").json()
    assert j["attempts"]["FIELD_VISIT"] == 1 and j["state"]["visit_id"]
    assert j["waiting_for"]["waiting_for"] == "shopkeeper"  # documents can still arrive (the employee collects them)
    client.post("/api/demo/advance-clock", json={"hours": 2})
    assert client.get(f"/api/journeys/{HERO}").json()["attempts"]["FIELD_VISIT"] == 1  # ladder finished: wait


def test_no_pan_reply_offers_form60(client):
    client.post(f"/api/journeys/{HERO}/start")
    v = client.post(f"/api/journeys/{HERO}/reply", json={"text": "mere paas PAN nahi hai"}).json()
    assert v["state"]["needed_docs"] == ["FORM60", "OVD"] and v["waiting_for"]["doc_type"] == "FORM60"
    msg = client.get(f"/api/merchants/{HERO}/chat").json()["messages"][-1]
    assert "60" in msg["text_hi"] and msg["sender"] == "agent"


def test_rejected_document_gets_a_specific_fix(client):
    client.post(f"/api/journeys/{HERO}/start")
    v = upload(client, HERO, "ovd_sharp.jpg", "PAN")  # wrong document for a PAN
    assert v["state"]["last_check"]["reason_code"] == "WRONG_DOCUMENT"
    assert v["waiting_for"]["doc_type"] == "PAN" and v["qr_status"] == "IN_PROGRESS"


# ------------------------------------------------------------ escalate

def test_two_low_confidence_uploads_escalate_and_wait_for_a_human(client):
    client.post(f"/api/journeys/{HERO}/start")
    upload(client, HERO, "pan_blurry.jpg", "PAN")
    v = upload(client, HERO, "pan_blurry.jpg", "PAN")
    assert v["waiting_for"]["waiting_for"] == "human_review" and v["qr_status"] == "ESCALATED"
    case = client.get("/api/review").json()["cases"][0]
    assert case["merchant_id"] == HERO and "confidence" in case["reason"]
    # the agent cannot be fed documents while a human decides
    with open(ASSETS / "pan_sharp.jpg", "rb") as f:
        assert client.post(f"/api/journeys/{HERO}/upload", files={"file": ("p.jpg", f)}, data={"doc_type": "PAN"}).status_code == 409
    v = client.post(f"/api/review/{case['id']}/decide", json={"decided_by": "Anjali", "decision": "APPROVE"}).json()
    assert v["waiting_for"] == {"waiting_for": "shopkeeper", "doc_type": "PAN"} and v["qr_status"] == "IN_PROGRESS"
    assert upload(client, HERO, "pan_sharp.jpg", "PAN")["state"]["last_check"]["decision"] == "ACCEPTED"


def test_name_mismatch_escalates(client, session):
    make_merchant(session, "T_MISMATCH", owner_name="Sunita Verma")
    client.post("/api/journeys/T_MISMATCH/start")
    v = upload(client, "T_MISMATCH", "pan_sharp.jpg", "PAN")
    assert v["state"]["last_check"]["reason_code"] == "NAME_MISMATCH"
    assert v["waiting_for"]["waiting_for"] == "human_review" and v["escalation_reason"] == "name mismatch"


def test_dispute_escalates(client):
    client.post(f"/api/journeys/{HERO}/start")
    v = client.post(f"/api/journeys/{HERO}/reply", json={"text": "yeh galat hai, maine kuch nahi kiya"}).json()
    assert v["waiting_for"]["waiting_for"] == "human_review"
    assert v["escalation_reason"] == "dispute raised by shopkeeper"


def test_mule_risk_escalates_at_triage_and_only_a_human_clears_it(client):
    mid = first_merchant(lambda m: mule_risk_score(m.risk_features) >= MULE_REVIEW_THRESHOLD and m.turnover_band != "ABOVE_40L")
    v = client.post(f"/api/journeys/{mid}/start").json()
    assert v["waiting_for"]["waiting_for"] == "human_review" and v["qr_status"] == "ESCALATED"
    assert v["escalation_reason"].startswith("mule-risk score") and "payer diversity" in v["escalation_reason"]
    case = client.get("/api/review").json()["cases"][0]
    assert case["merchant_id"] == mid and len(case["evidence"]["top_risk_features"]) >= 2  # why, not just a score
    case_id = v["state"]["review_case_id"]
    r = client.post(f"/api/review/{case_id}/decide", json={"decided_by": "Anjali", "decision": "REJECT"})
    assert r.status_code == 422  # a rejection must say why
    v = client.post(f"/api/review/{case_id}/decide", json={"decided_by": "Anjali", "decision": "REJECT",
                                                          "note": "Payments look like pass-through; refer to risk team"}).json()
    assert v["step"] == "CLOSED" and v["qr_status"] == "PAUSED"
    log = {e["action"]: e for e in v["timeline"]}
    assert log["REVIEW_DECIDED"]["actor"] == "human:Anjali" and log["REVIEW_DECIDED"]["payload"]["decision"] == "REJECT"
    assert log["JOURNEY_CLOSED"]["payload"]["note"] == "Payments look like pass-through; refer to risk team"
    assert client.get("/api/review?status=DECIDED").json()["cases"][0]["note"].startswith("Payments look")


def test_mule_risk_approved_by_a_human_continues_the_journey(client):
    mid = first_merchant(lambda m: mule_risk_score(m.risk_features) >= MULE_REVIEW_THRESHOLD and m.turnover_band != "ABOVE_40L")
    case_id = client.post(f"/api/journeys/{mid}/start").json()["state"]["review_case_id"]
    v = client.post(f"/api/review/{case_id}/decide", json={"decided_by": "Anjali", "decision": "APPROVE"}).json()
    assert v["waiting_for"]["waiting_for"] in ("shopkeeper", "field_employee")
    flag = next(r for r in evaluate(mid)["results"] if r["requirement"] == "NO_OPEN_RISK_FLAG")
    assert flag["passed"] and "human:Anjali" in flag["detail"]
    actions = [e["action"] for e in client.get(f"/api/journeys/{mid}").json()["timeline"]]
    after = actions[actions.index("REVIEW_DECIDED"):]  # the journey moves on after the human's approval
    assert "DOCUMENT_REQUESTED" in after or "VISIT_BOOKED" in after


def test_full_cdd_goes_to_human_review_and_is_never_auto_compliant(client):
    mid = first_merchant(lambda m: m.turnover_band == "ABOVE_40L")
    v = client.post(f"/api/journeys/{mid}/start").json()
    assert v["escalation_reason"] == "full due diligence required"
    v = client.post(f"/api/review/{v['state']['review_case_id']}/decide", json={"decided_by": "Anjali", "decision": "APPROVE"}).json()
    assert v["step"] == "CLOSED" and v["qr_status"] != "LIVE"


def test_ckycr_merchant_skips_documents_but_not_the_visit(client):
    mid = first_merchant(lambda m: m.in_ckycr and m.turnover_band != "ABOVE_40L"
                         and mule_risk_score(m.risk_features) < MULE_REVIEW_THRESHOLD)
    v = client.post(f"/api/journeys/{mid}/start").json()
    assert v["state"]["route"] == "CKYCR" and v["state"]["needed_docs"] == []
    assert v["waiting_for"]["waiting_for"] == "field_employee"


# ------------------------------------------------------------ guards and state

def test_reactivate_refuses_unless_the_rules_engine_says_compliant(client):
    client.post(f"/api/journeys/{HERO}/start")
    res = reactivate_qr(HERO)
    assert res["ok"] is False and "CPV_DONE" in res["failed"]
    assert client.get(f"/api/journeys/{HERO}").json()["qr_status"] == "IN_PROGRESS"


def test_journey_resumes_after_a_restart(client):
    client.post(f"/api/journeys/{HERO}/start")
    upload(client, HERO, "pan_sharp.jpg", "PAN")
    service.close_graph()  # as if the server restarted: state comes back from the SQLite checkpoint
    v = client.get(f"/api/journeys/{HERO}").json()
    assert v["state"]["accepted_docs"] == ["PAN"] and v["waiting_for"]["doc_type"] == "OVD"
    assert upload(client, HERO, "ovd_sharp.jpg", "OVD")["waiting_for"]["waiting_for"] == "field_employee"


def test_policy_rules():
    assert policy.ladder(True) == ["SOUNDBOX", "WHATSAPP", "IVR", "FIELD_VISIT"]
    assert policy.ladder(False) == ["WHATSAPP", "IVR", "FIELD_VISIT"]
    assert policy.classify_reply("मेरे पास पैन नहीं है") == "NO_PAN"
    assert policy.classify_reply("ye fraud hai") == "DISPUTE"
    assert policy.classify_reply("theek hai, bhejta hoon") == "OTHER"
    low = {"decision": "REJECTED", "reason_code": "BLURRY", "confidence": 0.4}
    assert policy.document_escalation(low, 1) is None and policy.document_escalation(low, 2)
    assert policy.document_escalation({**low, "reason_code": "NAME_MISMATCH", "confidence": 0.99}, 1) == "name mismatch"
    assert policy.tick_options(1.0, 0, 4)[0] == ["WAIT"]
    assert policy.tick_options(2.5, 0, 4)[0] == ["REQUEST_DOCUMENT", "WAIT"]
    assert policy.tick_options(9.0, 3, 4)[0] == ["WAIT"]


def test_a_stale_checkpoint_schema_is_rebuilt_instead_of_breaking_journeys(client):
    import sqlite3

    from app.config import settings
    service.close_graph()
    con = sqlite3.connect(settings.checkpoint_path)
    con.execute("DROP TABLE IF EXISTS checkpoints")
    con.execute("CREATE TABLE checkpoints(thread_id text, blob text)")  # layout left by an early scaffold
    con.commit()
    con.close()
    assert client.post(f"/api/journeys/{HERO}/start").json()["waiting_for"]["doc_type"] == "PAN"
