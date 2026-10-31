"""Deterministic policy: which actions are valid in each state, escalation conditions, the retry ladder, and
the accept-or-override step for every LLM proposal.

At each decision point the agent computes the valid actions and the policy's own default. The LLM proposes
one of the valid actions (its schema only allows those); the policy accepts it when it is valid and confident
enough, otherwise overrides it with the default. If the LLM is unavailable the policy decides alone, so a
journey never waits on the LLM. Every decision is written to the audit log.
"""
import logging
from dataclasses import asdict, dataclass
from typing import Optional

from .. import audit, llm
from ..scoring import MULE_REVIEW_THRESHOLD

log = logging.getLogger("qrwapsi.policy")

ALLOWED_ACTIONS = (
    "SEND_WHATSAPP",
    "PLAY_SOUNDBOX_PROMPT",
    "REQUEST_DOCUMENT",
    "VERIFY_DOCUMENT",
    "SCHEDULE_VISIT",
    "WAIT",
    "ESCALATE",
    "RUN_COMPLIANCE",
)

MIN_CONFIDENCE = 0.6          # below this an otherwise valid LLM proposal is overridden
RETRY_AFTER_H = 2             # simulated hours without a reply before the next rung of the ladder
DOC_LOW_CONFIDENCE = 0.8      # escalate when a document is still below this after DOC_ESCALATE_ATTEMPTS
DOC_ESCALATE_ATTEMPTS = 2

NO_PAN_PHRASES = ("no pan", "don't have pan", "dont have pan", "pan nahi", "pan nahin", "pan card nahi",
                  "पैन नहीं", "पैन कार्ड नहीं", "pan नहीं")
DISPUTE_PHRASES = ("dispute", "complaint", "fraud", "galat", "wrong", "shikayat", "शिकायत", "गलत", "धोखा", "not my")


# ------------------------------------------------------------ rules

def ladder(has_soundbox: bool) -> list[str]:
    """Contact ladder: Soundbox -> WhatsApp -> IVR -> field visit (Soundbox skipped when the shop has none)."""
    return (["SOUNDBOX"] if has_soundbox else []) + ["WHATSAPP", "IVR", "FIELD_VISIT"]


def triage_escalation(route: str, mule: dict) -> Optional[str]:
    if route == "FULL_CDD":
        return "full due diligence required"
    if mule["score"] >= MULE_REVIEW_THRESHOLD:
        return f"mule-risk score {mule['score']:.2f} >= {MULE_REVIEW_THRESHOLD}"
    return None


def document_escalation(check: dict, attempt_no: int) -> Optional[str]:
    if check["decision"] == "ACCEPTED":
        return None
    if check["reason_code"] == "NAME_MISMATCH":
        return "name mismatch"
    if attempt_no >= DOC_ESCALATE_ATTEMPTS and check["confidence"] < DOC_LOW_CONFIDENCE:
        return f"document confidence {check['confidence']:.2f} < {DOC_LOW_CONFIDENCE} after {attempt_no} attempts"
    return None


def classify_reply(text: str) -> str:
    """NO_PAN | DISPUTE | OTHER (keyword rules, Hindi and Hinglish)."""
    low = (text or "").lower()
    if any(p in low for p in DISPUTE_PHRASES):
        return "DISPUTE"
    if any(p in low for p in NO_PAN_PHRASES):
        return "NO_PAN"
    return "OTHER"


def tick_options(hours_since_contact: float, rung: int, rungs: int) -> tuple[list[str], str, str]:
    """Valid actions when the simulated clock moves and the shopkeeper has not replied."""
    if rung >= rungs - 1:
        return ["WAIT"], "WAIT", "contact ladder finished (field visit booked); waiting"
    if hours_since_contact < RETRY_AFTER_H:
        return ["WAIT"], "WAIT", f"{hours_since_contact:.1f} h since last contact, retry after {RETRY_AFTER_H} h"
    if hours_since_contact < 2 * RETRY_AFTER_H:
        return ["REQUEST_DOCUMENT", "WAIT"], "REQUEST_DOCUMENT", f"no reply for {hours_since_contact:.1f} h: next channel"
    return ["REQUEST_DOCUMENT"], "REQUEST_DOCUMENT", f"no reply for {hours_since_contact:.1f} h: waiting longer is not allowed"


# ------------------------------------------------------------ accept / override

@dataclass
class Decision:
    point: str
    valid: list[str]
    default: str
    policy_reason: str
    proposed: Optional[str]
    confidence: Optional[float]
    llm_reason: Optional[str]
    final: str
    verdict: str        # accepted | overrode | decided_alone
    summary: str


def decide(merchant_id: str, point: str, state_summary: dict, valid: list[str], default: str,
           policy_reason: str) -> Decision:
    """Ask the LLM to propose one of `valid`, then accept or override. Writes one audit entry (actor "policy")."""
    assert valid and default in valid and set(valid) <= set(ALLOWED_ACTIONS), (valid, default)
    proposal, llm_error = None, None
    if valid != ["WAIT"]:  # nothing to choose while simply waiting out the retry delay
        try:
            proposal = llm.propose_next_action({"merchant_id": merchant_id, "decision_point": point, **state_summary}, valid)
        except Exception as e:  # noqa: BLE001  (LLMUnavailable or anything else: the policy decides alone)
            llm_error = str(e)

    if proposal is None:
        final, verdict = default, "decided_alone"
        why = "only WAIT is valid" if valid == ["WAIT"] else f"LLM unavailable ({llm_error})"
        summary = f"Policy decided {final} alone: {why}"
    elif proposal.action not in valid:
        final, verdict = default, "overrode"
        summary = f"LLM proposed {proposal.action} (conf {proposal.confidence:.2f}) → policy overrode: not valid here, chose {final}"
    elif proposal.confidence < MIN_CONFIDENCE:
        final, verdict = default, "overrode"
        summary = (f"LLM proposed {proposal.action} (conf {proposal.confidence:.2f}) → policy overrode: confidence below "
                   f"{MIN_CONFIDENCE}, chose {final}")
    else:
        final, verdict = proposal.action, "accepted"
        summary = f"LLM proposed {proposal.action} (conf {proposal.confidence:.2f}) → policy accepted"

    d = Decision(point=point, valid=list(valid), default=default, policy_reason=policy_reason,
                 proposed=proposal.action if proposal else None, confidence=proposal.confidence if proposal else None,
                 llm_reason=proposal.reason if proposal else None, final=final, verdict=verdict, summary=summary)
    audit.log(merchant_id, "policy", "DECISION", asdict(d))
    log.info("[%s] %s: %s", merchant_id, point, summary)
    return d
