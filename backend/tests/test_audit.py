import hashlib

import pytest
from sqlalchemy import text
from sqlmodel import select

from app import audit
from app.db import engine
from app.models import AuditEntry


def seed_chain(session, mid="M0001", n=4):
    return [audit.log(mid, "agent", f"STEP_{i}", {"i": i, "msg": "आपका QR फिर से चालू"}, session) for i in range(n)]


def test_entries_are_chained(session):
    e = seed_chain(session)
    assert e[0].prev_hash == ""
    for a, b in zip(e, e[1:]):
        assert b.prev_hash == a.hash
    assert len({x.hash for x in e}) == len(e)
    assert audit.verify_chain("M0001", session) == {"ok": True, "broken_at": None, "merchant_id": None, "checked": 4}


def test_hash_is_sha256_of_prev_plus_canonical_json(session):
    e = audit.log("M0001", "policy", "X", {"b": 1, "a": 2}, session)
    body = audit.canonical_json({"merchant_id": "M0001", "ts": e.ts.replace(tzinfo=None).isoformat(),
                                 "actor": "policy", "action": "X", "payload": {"a": 2, "b": 1}})
    assert e.hash == hashlib.sha256(("" + body).encode()).hexdigest()


def test_chains_are_per_merchant(session):
    seed_chain(session, "M0001", 2)
    b = audit.log("M0002", "agent", "HELLO", {}, session)
    assert b.prev_hash == ""
    assert audit.verify_chain(None, session)["ok"]


def test_tampered_payload_is_detected(session):
    e = seed_chain(session)
    with engine.begin() as c:
        c.execute(text("UPDATE auditentry SET payload = :p WHERE id = :i"), {"p": '{"i": 99}', "i": e[1].id})
    res = audit.verify_chain("M0001", session)
    assert res["ok"] is False and res["broken_at"] == e[1].id
    assert audit.verify_chain(None, session)["broken_at"] == e[1].id


def test_tampered_actor_is_detected(session):
    e = seed_chain(session)
    with engine.begin() as c:
        c.execute(text("UPDATE auditentry SET actor = 'human:Mallory' WHERE id = :i"), {"i": e[2].id})
    assert audit.verify_chain("M0001", session)["broken_at"] == e[2].id


def test_deleted_entry_is_detected(session):
    e = seed_chain(session)
    with engine.begin() as c:
        c.execute(text("DELETE FROM auditentry WHERE id = :i"), {"i": e[1].id})
    res = audit.verify_chain("M0001", session)
    assert res["ok"] is False and res["broken_at"] == e[2].id


def test_other_merchants_chain_unaffected_by_tampering(session):
    e = seed_chain(session, "M0001")
    seed_chain(session, "M0002")
    with engine.begin() as c:
        c.execute(text("UPDATE auditentry SET action = 'FORGED' WHERE id = :i"), {"i": e[0].id})
    assert audit.verify_chain("M0002", session)["ok"] is True
    assert audit.verify_chain("M0001", session)["ok"] is False


def test_orm_refuses_update_and_delete(session):
    e = seed_chain(session, n=1)[0]
    row = session.exec(select(AuditEntry).where(AuditEntry.id == e.id)).one()
    row.action = "EDITED"
    session.add(row)
    with pytest.raises(RuntimeError, match="append-only"):
        session.commit()
    session.rollback()
    row = session.exec(select(AuditEntry).where(AuditEntry.id == e.id)).one()
    session.delete(row)
    with pytest.raises(RuntimeError, match="append-only"):
        session.commit()
    session.rollback()
    assert audit.verify_chain("M0001", session)["ok"]
