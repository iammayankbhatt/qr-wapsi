"""JourneyState: one LangGraph thread per merchant (thread_id = merchant_id). Plain JSON values only, so the
SqliteSaver checkpoint survives a server restart."""
from typing import Optional, TypedDict


class JourneyState(TypedDict, total=False):
    merchant_id: str
    route: str                      # SMALL_MERCHANT | CKYCR | FULL_CDD
    needed_docs: list[str]          # in collection order, e.g. ["PAN", "OVD"]; PAN becomes FORM60 on request
    accepted_docs: list[str]
    doc_attempts: dict[str, int]    # uploads checked per doc type
    channel_attempts: dict[str, int]  # contacts per channel: SOUNDBOX, WHATSAPP, IVR, FIELD_VISIT
    ladder_rung: int                # index into policy.ladder(): the channel used for the latest request
    last_contact_at: str            # simulated-clock ISO time of the latest request
    request_kind: str               # what request_document sends next: FIRST, RETRY, FIX, NEXT, FORM60, REPLY_ACK, AFTER_REVIEW
    event: dict                     # last event received while waiting (upload / reply / tick / field_done / review)
    last_check: dict                # trimmed result of the latest check_document
    action: str                     # the decided action; routes the graph
    escalation: Optional[dict]      # {reason, resume_to, evidence}
    review_case_id: Optional[int]
    visit_id: Optional[int]
    compliance: dict
    status: str                     # ACTIVE | LIVE | CLOSED


def current_doc(state: JourneyState) -> Optional[str]:
    """First needed document not yet accepted."""
    accepted = set(state.get("accepted_docs", []))
    return next((d for d in state.get("needed_docs", []) if d not in accepted), None)
