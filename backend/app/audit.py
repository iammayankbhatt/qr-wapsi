"""Append-only, hash-chained audit log. One chain per merchant.

hash = sha256(prev_hash + canonical_json(entry)); the first entry of a chain has prev_hash "".
The ORM refuses updates and deletes of AuditEntry rows; verify_chain() detects anything done
behind its back (edited payloads, removed or reordered rows).
"""
import hashlib
import json
import threading
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import event
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from .db import engine
from .models import AuditEntry

_lock = threading.Lock()
_APPEND_ATTEMPTS = 5


def canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def _ts_text(ts: datetime) -> str:
    # stored as UTC; SQLite hands it back naive, so hash the naive-UTC text both times
    return ts.replace(tzinfo=None).isoformat()


def compute_hash(prev_hash: str, entry: AuditEntry) -> str:
    body = {
        "merchant_id": entry.merchant_id,
        "ts": _ts_text(entry.ts),
        "actor": entry.actor,
        "action": entry.action,
        "payload": entry.payload,
    }
    return hashlib.sha256((prev_hash + canonical_json(body)).encode("utf-8")).hexdigest()


def log(merchant_id: str, actor: str, action: str, payload: Optional[dict] = None,
        session: Optional[Session] = None) -> AuditEntry:
    """Append one entry to the merchant's chain and return it."""
    if session is None:
        with Session(engine) as own:
            return log(merchant_id, actor, action, payload, own)

    with _lock:  # serialises threads; the (merchant_id, prev_hash) constraint serialises processes
        for attempt in range(_APPEND_ATTEMPTS):
            last = session.exec(
                select(AuditEntry).where(AuditEntry.merchant_id == merchant_id).order_by(AuditEntry.id.desc())
                .execution_options(populate_existing=True)
            ).first()
            entry = AuditEntry(
                merchant_id=merchant_id,
                ts=datetime.now(timezone.utc),
                actor=actor,
                action=action,
                # round-trip through JSON so what is hashed is exactly what the database returns
                payload=json.loads(canonical_json(payload or {})),
                prev_hash=last.hash if last else "",
            )
            entry.hash = compute_hash(entry.prev_hash, entry)
            session.add(entry)
            try:
                session.commit()
            except IntegrityError:  # another process appended first: re-read the head and try again
                session.rollback()
                if attempt == _APPEND_ATTEMPTS - 1:
                    raise
                continue
            session.refresh(entry)
            return entry


def _verify_one(entries: list[AuditEntry]) -> Optional[int]:
    prev = ""
    for e in entries:
        if e.prev_hash != prev or e.hash != compute_hash(prev, e):
            return e.id
        prev = e.hash
    return None


def verify_chain(merchant_id: Optional[str] = None, session: Optional[Session] = None) -> dict:
    """Check one merchant's chain, or every chain when merchant_id is None.

    Returns {ok, broken_at (id of the first bad entry or None), merchant_id (of the broken chain), checked}.
    """
    if session is None:
        with Session(engine) as own:
            return verify_chain(merchant_id, own)

    query = select(AuditEntry).order_by(AuditEntry.id)
    if merchant_id is not None:
        query = query.where(AuditEntry.merchant_id == merchant_id)
    chains: dict[str, list[AuditEntry]] = {}
    # always re-read from the database: never trust rows cached in the session
    for e in session.exec(query.execution_options(populate_existing=True)).all():
        chains.setdefault(e.merchant_id, []).append(e)

    checked = sum(len(v) for v in chains.values())
    for mid, entries in chains.items():
        bad = _verify_one(entries)
        if bad is not None:
            return {"ok": False, "broken_at": bad, "merchant_id": mid, "checked": checked}
    return {"ok": True, "broken_at": None, "merchant_id": None, "checked": checked}


def entries_for(merchant_id: str, session: Session) -> list[AuditEntry]:
    query = select(AuditEntry).where(AuditEntry.merchant_id == merchant_id).order_by(AuditEntry.id)
    return list(session.exec(query.execution_options(populate_existing=True)).all())


@event.listens_for(AuditEntry, "before_update")
def _block_update(mapper, connection, target):
    raise RuntimeError("audit log is append-only: updates are not allowed")


@event.listens_for(AuditEntry, "before_delete")
def _block_delete(mapper, connection, target):
    raise RuntimeError("audit log is append-only: deletes are not allowed")
