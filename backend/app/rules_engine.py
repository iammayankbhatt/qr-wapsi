"""Deterministic compliance checks. Pure Python, no LLM: only evaluate() can say a merchant is compliant.

Facts come from rows other components persist:
  * Document (decision ACCEPTED) for PAN / FORM60 / OVD. For PAN/FORM60, extracted_fields must carry
    authority_verified=True (set by the PAN-verification step) and extracted_fields["name"].
  * Document with doc_type "CKYCR": the fetched CKYCR record (extracted_fields: ckyc_id, name).
  * Visit: CPV is satisfied only by a completed visit confirmed by a field employee (an Employee id)
    with a geo-tag and a signboard photo. Nothing the agent does can fill those in.
  * ReviewCase: an OPEN case is a risk flag. A high mule score also blocks until a human clears it.
"""
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Callable, Optional

import yaml
from rapidfuzz import fuzz
from sqlmodel import Session, select

from . import audit
from .db import engine
from .models import Document, Employee, Merchant, ReviewCase, Visit
from .scoring import MULE_REVIEW_THRESHOLD, mule_risk_score

CONFIG_PATH = Path(__file__).with_name("rules_config.yaml")
HUMAN_CLEAR_DECISION = "APPROVE"  # ReviewCase.decision a human records to clear a flagged merchant


@lru_cache
def load_config() -> dict:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


def determine_route(m: Merchant, cfg: Optional[dict] = None) -> str:
    cfg = cfg or load_config()
    if m.turnover_band in cfg["full_cdd_turnover_bands"]:
        return "FULL_CDD"
    return "CKYCR" if m.in_ckycr else "SMALL_MERCHANT"


@dataclass
class Ctx:
    merchant: Merchant
    docs: dict[str, Document]          # latest ACCEPTED document per doc_type
    visit: Optional[Visit]             # latest completed visit
    employee_ids: set[str]
    cases: list[ReviewCase]
    cfg: dict


Check = tuple[bool, Optional[str], str]  # passed, evidence_ref, detail


def _norm(name: str) -> str:
    return " ".join(re.sub(r"[^A-Za-z0-9 ]", " ", name or "").upper().split())


def name_match_score(a: str, b: str) -> float:
    """0-100 fuzzy match of two person names, ignoring case, punctuation and word order."""
    return fuzz.token_sort_ratio(_norm(a), _norm(b))


def _pan_or_form60(c: Ctx) -> Check:
    for t in ("PAN", "FORM60"):
        d = c.docs.get(t)
        if d and d.extracted_fields.get("authority_verified") is True:
            return True, f"document:{d.id}", f"{t} accepted and verified with the issuing authority"
        if d:
            return False, f"document:{d.id}", f"{t} accepted but not verified with the issuing authority"
    return False, None, "No accepted PAN or Form 60"


def _ovd(c: Ctx) -> Check:
    d = c.docs.get("OVD")
    return (True, f"document:{d.id}", "OVD collected and accepted") if d else (False, None, "No accepted OVD")


def _ckycr(c: Ctx) -> Check:
    d = c.docs.get("CKYCR")
    if d and d.extracted_fields.get("ckyc_id"):
        return True, f"document:{d.id}", f"CKYCR record {d.extracted_fields['ckyc_id']} verified"
    return False, None, "No verified CKYCR record"


def _name_match(c: Ctx, route: str) -> Check:
    types = ("CKYCR",) if route == "CKYCR" else ("PAN", "FORM60", "OVD")
    docs = [c.docs[t] for t in types if t in c.docs]
    if not docs:
        return False, None, "No accepted identity document to compare against"
    threshold = c.cfg["name_match_threshold"]
    scores = [(d, name_match_score(c.merchant.owner_name, d.extracted_fields.get("name") or "")) for d in docs]
    refs = ",".join(f"document:{d.id}" for d, _ in scores)
    summary = ", ".join(f"{d.doc_type} {s:.0f}" for d, s in scores)
    ok = all(s >= threshold for _, s in scores)
    return ok, refs, f"Match scores vs '{c.merchant.owner_name}' (need >= {threshold}): {summary}"


def _cpv(c: Ctx) -> Check:
    v = c.visit
    if v is None:
        return False, None, "No completed in-person visit"
    ref = f"visit:{v.id}"
    if v.confirmed_by not in c.employee_ids:
        return False, ref, "Visit not confirmed by a field employee"
    if not v.geo_tag:
        return False, ref, "Visit has no geo-tag"
    if not v.signboard_photo:
        return False, ref, "Visit has no signboard photo"
    return True, ref, f"CPV completed by {v.confirmed_by}"


def _no_risk_flag(c: Ctx) -> Check:
    open_cases = [x for x in c.cases if x.status == "OPEN"]
    if open_cases:
        return False, f"review_case:{open_cases[0].id}", f"Open review case: {open_cases[0].reason}"
    mule = mule_risk_score(c.merchant.risk_features)
    if mule >= MULE_REVIEW_THRESHOLD:
        cleared = [x for x in c.cases if x.status == "DECIDED" and x.decision == HUMAN_CLEAR_DECISION
                   and (x.decided_by or "").startswith("human:")]
        if cleared:
            return True, f"review_case:{cleared[-1].id}", f"Mule risk {mule:.2f} cleared by {cleared[-1].decided_by}"
        return False, None, f"Mule risk {mule:.2f} >= {MULE_REVIEW_THRESHOLD}: human review required"
    return True, None, f"No open review case; mule risk {mule:.2f}"


CHECKS: dict[str, Callable[..., Check]] = {
    "PAN_OR_FORM60_VERIFIED": _pan_or_form60,
    "OVD_COLLECTED": _ovd,
    "CKYCR_RECORD_VERIFIED": _ckycr,
    "NAME_MATCH": _name_match,
    "CPV_DONE": _cpv,
    "NO_OPEN_RISK_FLAG": _no_risk_flag,
}


def _load_ctx(m: Merchant, cfg: dict, session: Session) -> Ctx:
    docs: dict[str, Document] = {}
    for d in session.exec(select(Document).where(Document.merchant_id == m.id, Document.decision == "ACCEPTED").order_by(Document.id)):
        docs[d.doc_type] = d  # later rows overwrite earlier ones: latest accepted wins
    visit = session.exec(select(Visit).where(Visit.merchant_id == m.id, Visit.completed_at != None)  # noqa: E711
                         .order_by(Visit.id.desc())).first()
    return Ctx(
        merchant=m, docs=docs, visit=visit,
        employee_ids={e.id for e in session.exec(select(Employee))},
        cases=list(session.exec(select(ReviewCase).where(ReviewCase.merchant_id == m.id).order_by(ReviewCase.id))),
        cfg=cfg,
    )


def evaluate(merchant_id: str, session: Optional[Session] = None, *, write_audit: bool = True) -> dict:
    """-> {merchant_id, route, results: [{requirement, passed, evidence_ref, checked_at, detail}], compliant, review_reason}.

    Writes one audit entry (actor "rules_engine") per call; write_audit=False is a read-only preview for screens.
    """
    if session is None:
        with Session(engine) as own:
            return evaluate(merchant_id, own, write_audit=write_audit)

    m = session.get(Merchant, merchant_id)
    if m is None:
        raise KeyError(merchant_id)
    cfg = load_config()
    route = determine_route(m, cfg)
    route_cfg = cfg["routes"][route]
    ctx = _load_ctx(m, cfg, session)

    results = []
    for req in route_cfg["requirements"]:
        check = CHECKS[req]
        passed, ref, detail = check(ctx, route) if req == "NAME_MATCH" else check(ctx)
        results.append({"requirement": req, "passed": bool(passed), "evidence_ref": ref,
                        "checked_at": datetime.now(timezone.utc).isoformat(), "detail": detail})

    review_reason = route_cfg.get("always_human_review")
    compliant = review_reason is None and bool(results) and all(r["passed"] for r in results)
    out = {"merchant_id": merchant_id, "route": route, "results": results,
           "compliant": compliant, "review_reason": review_reason}

    if not write_audit:
        return out
    audit.log(merchant_id, "rules_engine", "COMPLIANCE_EVALUATED", {
        "route": route, "compliant": compliant, "review_reason": review_reason,
        "results": [{k: r[k] for k in ("requirement", "passed", "evidence_ref")} for r in results],
    }, session)
    return out
