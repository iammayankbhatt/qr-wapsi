"""Server-Sent Events. Producers (API process and MCP tool process) write Event rows; this streams new rows."""
import asyncio
import json
from typing import Optional

from fastapi import APIRouter, Query, Request
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import func
from sqlmodel import Session, select
from sse_starlette.sse import EventSourceResponse, ServerSentEvent

from ..db import engine
from ..models import Event

router = APIRouter()

POLL_S = 0.5


def _fetch(after: int, merchant_id: Optional[str] = None, limit: int = 200) -> list[dict]:
    with Session(engine) as s:
        q = select(Event).where(Event.id > after).order_by(Event.id).limit(limit)
        if merchant_id:
            q = q.where(Event.merchant_id == merchant_id)
        return [{"id": e.id, "ts": e.ts.isoformat(), "type": e.type, "merchant_id": e.merchant_id, "data": e.data}
                for e in s.exec(q)]


def _last_id() -> int:
    with Session(engine) as s:
        return s.exec(select(func.max(Event.id))).one() or 0


@router.get("/events")
async def stream(request: Request, since: Optional[int] = None, merchant_id: Optional[str] = None):
    """SSE stream. Starts after `since`, the Last-Event-ID header, or (by default) the newest event."""
    header = request.headers.get("last-event-id")
    after = since if since is not None else int(header) if header and header.isdigit() else await run_in_threadpool(_last_id)

    async def gen():
        nonlocal after
        # Send something at once: proxies (e.g. Vite's dev proxy) hold back the response headers until the
        # first body bytes, which would otherwise leave the browser "connecting" until the first ping.
        yield ServerSentEvent(comment="connected", retry=2000)
        while not await request.is_disconnected():
            for e in await run_in_threadpool(_fetch, after, merchant_id):
                after = e["id"]
                yield {"id": str(e["id"]), "event": e["type"], "data": json.dumps(e, ensure_ascii=False)}
            await asyncio.sleep(POLL_S)

    return EventSourceResponse(gen(), ping=15)


@router.get("/events/recent")
def recent(since: int = 0, merchant_id: Optional[str] = None, limit: int = Query(200, ge=1, le=1000)):
    """Plain JSON of events after `since` (for polling clients and tests)."""
    return {"events": _fetch(since, merchant_id, limit)}
