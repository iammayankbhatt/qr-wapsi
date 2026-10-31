from datetime import datetime

import pytest

from app import audit
from app.models import Document, ReviewCase, Visit
from app.rules_engine import evaluate
from tests.conftest import make_merchant

PAN_FIELDS = {"name": "RAMESH SHARMA", "pan": "ABCPS1234K", "authority_verified": True}


def add_docs(s, mid, pan=True, ovd=True, name="RAMESH SHARMA", verified=True):
    if pan:
        s.add(Document(merchant_id=mid, doc_type="PAN", file_path="x", decision="ACCEPTED",
                       extracted_fields={**PAN_FIELDS, "name": name, "authority_verified": verified}))
    if ovd:
        s.add(Document(merchant_id=mid, doc_type="OVD", file_path="x", decision="ACCEPTED",
                       extracted_fields={"name": name}))
    s.commit()


def add_cpv(s, mid, confirmed_by="E01", geo=True, photo=True, completed=True):
    s.add(Visit(merchant_id=mid, employee_id="E01", scheduled_at=datetime(2026, 11, 2, 15, 10),
                geo_tag={"lat": 28.627, "lng": 77.365} if geo else None,
                signboard_photo="sign.jpg" if photo else None, confirmed_by=confirmed_by,
                completed_at=datetime(2026, 11, 2, 15, 40) if completed else None))
    s.commit()


def passed(res):
    return {r["requirement"]: r["passed"] for r in res["results"]}


def small_ready(s, mid="T_SMALL"):
    make_merchant(s, mid)
    add_docs(s, mid)
    add_cpv(s, mid)
    return mid


# ---- SMALL_MERCHANT ----

def test_small_merchant_all_requirements_met_is_compliant(session):
    res = evaluate(small_ready(session), session)
    assert res["route"] == "SMALL_MERCHANT"
    assert set(passed(res)) == {"PAN_OR_FORM60_VERIFIED", "OVD_COLLECTED", "NAME_MATCH", "CPV_DONE", "NO_OPEN_RISK_FLAG"}
    assert res["compliant"] is True and all(passed(res).values())
    evidenced = ("PAN_OR_FORM60_VERIFIED", "OVD_COLLECTED", "CPV_DONE")
    assert all(r["evidence_ref"] for r in res["results"] if r["requirement"] in evidenced)


def test_nothing_collected_is_not_compliant(session):
    make_merchant(session, "T_EMPTY")
    res = evaluate("T_EMPTY", session)
    assert res["compliant"] is False
    failing = {k for k, v in passed(res).items() if not v}
    assert failing == {"PAN_OR_FORM60_VERIFIED", "OVD_COLLECTED", "NAME_MATCH", "CPV_DONE"}


def test_cpv_missing_is_not_compliant(session):
    make_merchant(session, "T_NOCPV")
    add_docs(session, "T_NOCPV")
    res = evaluate("T_NOCPV", session)
    assert [k for k, v in passed(res).items() if not v] == ["CPV_DONE"]
    assert res["compliant"] is False


@pytest.mark.parametrize("kw", [
    dict(confirmed_by="agent"),      # not a field employee
    dict(confirmed_by=None),
    dict(geo=False),
    dict(photo=False),
    dict(completed=False),           # scheduled but never completed
])
def test_cpv_needs_a_complete_employee_confirmed_visit(session, kw):
    make_merchant(session, "T_CPV")
    add_docs(session, "T_CPV")
    add_cpv(session, "T_CPV", **kw)
    res = evaluate("T_CPV", session)
    assert passed(res)["CPV_DONE"] is False and res["compliant"] is False


def test_unverified_pan_fails(session):
    make_merchant(session, "T_PAN")
    add_docs(session, "T_PAN", verified=False)
    add_cpv(session, "T_PAN")
    res = evaluate("T_PAN", session)
    assert passed(res)["PAN_OR_FORM60_VERIFIED"] is False and res["compliant"] is False


def test_form60_can_replace_pan(session):
    make_merchant(session, "T_F60")
    session.add(Document(merchant_id="T_F60", doc_type="FORM60", file_path="x", decision="ACCEPTED",
                         extracted_fields={"name": "RAMESH SHARMA", "authority_verified": True}))
    session.commit()
    add_docs(session, "T_F60", pan=False)
    add_cpv(session, "T_F60")
    assert evaluate("T_F60", session)["compliant"] is True


def test_rejected_documents_do_not_count(session):
    make_merchant(session, "T_REJ")
    session.add(Document(merchant_id="T_REJ", doc_type="OVD", file_path="x", decision="REJECTED",
                         extracted_fields={"name": "RAMESH SHARMA"}))
    session.commit()
    assert passed(evaluate("T_REJ", session))["OVD_COLLECTED"] is False


def test_name_mismatch_fails_but_spelling_noise_passes(session):
    make_merchant(session, "T_NAME")
    add_docs(session, "T_NAME", name="SURESH KUMAR")
    add_cpv(session, "T_NAME")
    res = evaluate("T_NAME", session)
    assert passed(res)["NAME_MATCH"] is False and res["compliant"] is False

    make_merchant(session, "T_NAME2")
    add_docs(session, "T_NAME2", name="Sharma, Ramesh")
    assert passed(evaluate("T_NAME2", session))["NAME_MATCH"] is True


def test_open_review_case_blocks_until_decided(session):
    mid = small_ready(session)
    case = ReviewCase(merchant_id=mid, reason="dispute")
    session.add(case)
    session.commit()
    res = evaluate(mid, session)
    assert passed(res)["NO_OPEN_RISK_FLAG"] is False and res["compliant"] is False
    case.status = "DECIDED"
    session.add(case)
    session.commit()
    assert evaluate(mid, session)["compliant"] is True


def test_high_mule_risk_blocks_until_human_clears(session):
    mule = {"payer_diversity": 0.05, "spike_ratio": 5.0, "round_amount_share": 0.9, "night_share": 0.4}
    make_merchant(session, "T_MULE", risk_features=mule)
    add_docs(session, "T_MULE")
    add_cpv(session, "T_MULE")
    assert passed(evaluate("T_MULE", session))["NO_OPEN_RISK_FLAG"] is False
    # a non-human decision is not enough
    session.add(ReviewCase(merchant_id="T_MULE", reason="mule", status="DECIDED", decision="APPROVE", decided_by="agent"))
    session.commit()
    assert evaluate("T_MULE", session)["compliant"] is False
    session.add(ReviewCase(merchant_id="T_MULE", reason="mule", status="DECIDED", decision="APPROVE", decided_by="human:Asha"))
    session.commit()
    assert evaluate("T_MULE", session)["compliant"] is True


# ---- CKYCR ----

def test_ckycr_route(session):
    make_merchant(session, "T_CK", in_ckycr=True)
    add_cpv(session, "T_CK")
    res = evaluate("T_CK", session)
    assert res["route"] == "CKYCR"
    assert set(passed(res)) == {"CKYCR_RECORD_VERIFIED", "NAME_MATCH", "CPV_DONE", "NO_OPEN_RISK_FLAG"}
    assert res["compliant"] is False  # no CKYCR record yet

    session.add(Document(merchant_id="T_CK", doc_type="CKYCR", file_path="", decision="ACCEPTED",
                         extracted_fields={"ckyc_id": "SYN-0001", "name": "RAMESH SHARMA"}))
    session.commit()
    res = evaluate("T_CK", session)
    assert res["compliant"] is True and all(passed(res).values())


def test_ckycr_route_still_needs_cpv(session):
    make_merchant(session, "T_CK2", in_ckycr=True)
    session.add(Document(merchant_id="T_CK2", doc_type="CKYCR", file_path="", decision="ACCEPTED",
                         extracted_fields={"ckyc_id": "SYN-0002", "name": "RAMESH SHARMA"}))
    session.commit()
    res = evaluate("T_CK2", session)
    assert passed(res)["CPV_DONE"] is False and res["compliant"] is False


# ---- FULL_CDD ----

@pytest.mark.parametrize("in_ckycr", [False, True])
def test_full_cdd_is_never_compliant(session, in_ckycr):
    make_merchant(session, "T_BIG", turnover_band="ABOVE_40L", in_ckycr=in_ckycr)
    add_docs(session, "T_BIG")
    add_cpv(session, "T_BIG")
    session.add(Document(merchant_id="T_BIG", doc_type="CKYCR", file_path="", decision="ACCEPTED",
                         extracted_fields={"ckyc_id": "X", "name": "RAMESH SHARMA"}))
    session.commit()
    res = evaluate("T_BIG", session)
    assert res["route"] == "FULL_CDD"
    assert res["compliant"] is False
    assert res["review_reason"] == "full due diligence required"


# ---- audit ----

def test_every_evaluation_writes_a_rules_engine_audit_entry(session):
    mid = small_ready(session)
    evaluate(mid, session)
    evaluate(mid, session)
    entries = audit.entries_for(mid, session)
    assert [e.actor for e in entries] == ["rules_engine", "rules_engine"]
    assert entries[0].action == "COMPLIANCE_EVALUATED" and entries[0].payload["compliant"] is True
    assert audit.verify_chain(mid, session)["ok"]


def test_unknown_merchant_raises(session):
    with pytest.raises(KeyError):
        evaluate("NOPE", session)
