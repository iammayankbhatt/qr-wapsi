"""Run, resume and inspect journeys. thread_id = merchant_id; checkpoints in data/checkpoints.db, so a journey
picks up where it was after a server restart."""
import logging
import sqlite3
import threading
from collections import defaultdict
from typing import Any, Optional

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command
from sqlmodel import Session, select

from ..config import settings
from ..db import engine
from ..models import Journey

log = logging.getLogger("qrwapsi.agent")

_graph = None
_conn: Optional[sqlite3.Connection] = None
_graph_lock = threading.Lock()
_merchant_locks: defaultdict[str, threading.Lock] = defaultdict(threading.Lock)


class JourneyConflict(Exception):
    """The journey is not in a state that accepts this request (HTTP 409)."""


def _ensure_checkpoint_schema(conn: sqlite3.Connection) -> None:
    """SqliteSaver creates its tables with IF NOT EXISTS, so a stale table of the same name from an older layout
    would break every call ("no such column: checkpoint_id"). Drop incompatible tables; SqliteSaver recreates them."""
    cols = {row[1] for row in conn.execute("PRAGMA table_info(checkpoints)")}
    if cols and "checkpoint_id" not in cols:
        log.warning("checkpoints.db has an incompatible schema %s; recreating it (stored journeys are lost)", sorted(cols))
        conn.execute("DROP TABLE IF EXISTS checkpoints")
        conn.execute("DROP TABLE IF EXISTS writes")
        conn.commit()


def get_graph():
    global _graph, _conn
    with _graph_lock:
        if _graph is None:
            from .graph import build_graph
            settings.DATA_DIR.mkdir(parents=True, exist_ok=True)
            _conn = sqlite3.connect(str(settings.checkpoint_path), check_same_thread=False)
            _ensure_checkpoint_schema(_conn)
            _graph = build_graph().compile(checkpointer=SqliteSaver(_conn))
        return _graph


def close_graph() -> None:
    """Drop the compiled graph and its checkpoint connection (as a server restart would)."""
    global _graph, _conn
    with _graph_lock:
        if _conn is not None:
            _conn.close()
        _graph, _conn = None, None


def _cfg(mid: str) -> dict:
    return {"configurable": {"thread_id": mid}}


def _waiting(snapshot) -> Optional[dict]:
    for task in snapshot.tasks:
        for intr in getattr(task, "interrupts", ()):
            return intr.value
    return None


def snapshot(mid: str) -> dict:
    snap = get_graph().get_state(_cfg(mid))
    return {"started": bool(snap.values), "values": dict(snap.values or {}), "next": list(snap.next),
            "waiting": _waiting(snap)}


def start(mid: str) -> dict:
    """Start a journey, or continue one interrupted by a crash. Starting an active journey is a no-op."""
    g = get_graph()
    with _merchant_locks[mid]:
        snap = g.get_state(_cfg(mid))
        if not snap.values:
            g.invoke({"merchant_id": mid}, _cfg(mid))
        elif snap.next and _waiting(snap) is None:
            g.invoke(None, _cfg(mid))  # a node failed mid-run (e.g. server stopped): retry it
    return snapshot(mid)


def resume(mid: str, event: dict[str, Any], expect: str) -> dict:
    """Deliver an event to a journey that is waiting for `expect` (shopkeeper | field_employee | human_review)."""
    g = get_graph()
    with _merchant_locks[mid]:
        waiting = _waiting(g.get_state(_cfg(mid)))
        if waiting is None or waiting.get("waiting_for") != expect:
            now = waiting.get("waiting_for") if waiting else "nothing"
            raise JourneyConflict(f"journey {mid} is not waiting for {expect} (waiting for {now})")
        g.invoke(Command(resume=event), _cfg(mid))
    return snapshot(mid)


def tick_all() -> list[str]:
    """After the simulated clock moves, nudge every journey waiting on the shopkeeper (retry ladder)."""
    with Session(engine) as s:
        mids = list(s.exec(select(Journey.merchant_id).where(Journey.current_step == "COLLECT")))
    resumed = []
    for mid in mids:
        try:
            resume(mid, {"type": "tick"}, "shopkeeper")
            resumed.append(mid)
        except JourneyConflict:
            pass
    return resumed
