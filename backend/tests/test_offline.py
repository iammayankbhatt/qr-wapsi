"""Replay mode with the network off: the guard blocks outside calls, and live screens survive a demo reset."""
import socket

import pytest
from fastapi.testclient import TestClient

from app import netguard
from app.main import app


def test_guard_blocks_outside_calls_and_allows_loopback():
    before = len(netguard.blocked)
    with pytest.raises(ConnectionRefusedError):
        socket.getaddrinfo("api.sarvam.ai", 443)
    with pytest.raises(ConnectionRefusedError):
        socket.create_connection(("142.250.0.1", 443), timeout=1)
    assert len(netguard.blocked) == before + 2
    assert socket.getaddrinfo("127.0.0.1", 80)  # loopback still works


def test_system_reports_the_guard_and_never_probes_in_replay():
    with TestClient(app) as c:
        info = c.get("/api/system?probe=true").json()
    assert info["offline_guard"]["active"] is True
    assert info["reachability"]["llm"]["status"] == "replay" and info["reachability"]["sarvam"]["status"] == "replay"


def test_event_stream_continues_after_a_demo_reset():
    """Event ids restart at 1 after a reset; the stream must notice and keep delivering (not stall)."""
    import asyncio

    from app.events import publish
    from app.routers import events as ev
    from scripts.seed import reset_all

    for i in range(5):
        publish("test.before", None, {"i": i})

    class FakeRequest:
        headers: dict = {}

        def __init__(self):
            self.n = 0

        async def is_disconnected(self):
            self.n += 1
            return self.n > 6

    async def collect():
        resp = await ev.stream(FakeRequest())
        out, gen = [], resp.body_iterator
        first = await gen.__anext__()  # the immediate "connected" comment
        out.append(first)
        reset_all()  # ids start again at 1
        publish("demo.reset", None, {})
        async for item in gen:
            out.append(item)
        return out

    items = asyncio.run(collect())
    assert any(isinstance(i, dict) and i.get("event") == "demo.reset" for i in items)


def test_unhandled_errors_are_logged_and_friendly(monkeypatch, caplog):
    from app.agent import service

    def boom(mid):
        raise RuntimeError("database exploded")

    monkeypatch.setattr(service, "start", boom)
    with TestClient(app, raise_server_exceptions=False) as c:
        r = c.post("/api/journeys/M0001/start")
    assert r.status_code == 500 and "full error is in the server log" in r.json()["detail"]
    assert "database exploded" not in r.json()["detail"]
    assert any("unhandled error" in rec.getMessage() and rec.exc_info for rec in caplog.records)


def test_reset_is_fast_and_clean():
    with TestClient(app) as c:
        c.post("/api/journeys/M0001/start")
        r = c.post("/api/demo/reset").json()
        assert r["seconds"] < 5 and r["merchants"] == 1000
        j = c.get("/api/journeys/M0001").json()
        assert j["started"] is False and j["qr_status"] == "PAUSED" and j["timeline"] == []
        assert c.get("/api/stats").json()["qr_status"]["PAUSED"] == 1000
        assert c.get("/api/merchants/M0001/chat").json()["messages"] == []


def test_simulate_no_reply_never_moves_the_clock_when_refused():
    with TestClient(app) as c:
        c.post("/api/demo/reset")
        before = c.get("/api/demo/clock").json()["now"]
        r = c.post("/api/demo/no-reply", json={"merchant_id": "M0001"})  # not started
        assert r.status_code == 409 and "clock was not moved" in r.json()["detail"]
        assert c.get("/api/demo/clock").json()["now"] == before
        c.post("/api/journeys/M0001/start")
        assert c.post("/api/demo/no-reply", json={"merchant_id": "M0001"}).json()["attempts"]["WHATSAPP"] == 2


def test_reset_while_screens_are_reading_never_errors():
    """Reset is safe mid-demo: screens polling during resets never see a missing table or a server error."""
    import threading

    from scripts.seed import reset_all
    errors, polls, stop, polling = [], [0], threading.Event(), threading.Event()
    paths = ("/api/queue?limit=10", "/api/stats", "/api/audit/recent", "/api/journeys/M0001", "/api/field/route?employee_id=E04")

    with TestClient(app, raise_server_exceptions=False) as c:  # a server error becomes a 500, not a dead thread
        def reader():
            while not stop.is_set():
                for path in paths:
                    try:
                        r = c.get(path)
                        if r.status_code != 200:
                            errors.append((path, r.status_code))
                    except Exception as e:  # noqa: BLE001
                        errors.append((path, repr(e)))
                    polls[0] += 1
                    polling.set()

        t = threading.Thread(target=reader)
        t.start()
        try:
            assert polling.wait(10)
            start = polls[0]
            resets = 0
            while resets < 8 or polls[0] - start < 40:  # make sure many reads overlap the resets
                reset_all()
                resets += 1
        finally:
            stop.set()
            t.join()
    assert polls[0] - start >= 40 and errors == [], errors[:5]
