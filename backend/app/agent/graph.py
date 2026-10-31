"""The re-KYC journey as a LangGraph StateGraph (one thread per merchant, checkpointed in SQLite).

    triage ─► request_document ─► collect_document ◄─┐ (WAIT / tick)
                    ▲                  │  upload      │
                    │ FIX / NEXT        ▼              │
                    └────────── verify_document ──────┘
                                       │ all docs accepted
                                       ▼
                               schedule_visit ─► field_wait ─► compliance ─► reactivate ─► END
    any of triage / collect / verify / compliance ─► escalate ─► human_review ─► (resume) | closed ─► END

Every node sets state["action"]; route() maps it to the next node.
"""
from langgraph.graph import END, START, StateGraph

from . import nodes
from .state import JourneyState

ROUTES = {
    "REQUEST_DOCUMENT": "request_document",
    "SEND_WHATSAPP": "request_document",
    "VERIFY_DOCUMENT": "verify_document",
    "SCHEDULE_VISIT": "schedule_visit",
    "WAIT": "collect_document",
    "WAIT_FIELD": "field_wait",
    "RUN_COMPLIANCE": "compliance",
    "REACTIVATE": "reactivate",
    "ESCALATE": "escalate",
    "CLOSE": "closed",
    "DONE": END,
}
DESTINATIONS = sorted(set(ROUTES.values()) - {END}) + [END]


def route(state: JourneyState) -> str:
    return ROUTES[state["action"]]


def build_graph() -> StateGraph:
    g = StateGraph(JourneyState)
    for name in ("triage", "request_document", "collect_document", "verify_document", "schedule_visit",
                 "field_wait", "compliance", "reactivate", "escalate", "human_review", "closed"):
        g.add_node(name, getattr(nodes, name))
    g.add_edge(START, "triage")
    g.add_edge("request_document", "collect_document")
    g.add_edge("escalate", "human_review")
    g.add_edge("closed", END)
    for name in ("triage", "collect_document", "verify_document", "schedule_visit", "field_wait", "compliance",
                 "reactivate", "human_review"):
        g.add_conditional_edges(name, route, DESTINATIONS)
    return g
