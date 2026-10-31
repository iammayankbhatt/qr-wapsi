"""Publish UI events. Rows go to the Event table; /api/events streams them as Server-Sent Events."""
import json
import logging
from typing import Optional

from sqlmodel import Session

from .db import engine
from .models import Event

log = logging.getLogger("qrwapsi.events")


def publish(type: str, merchant_id: Optional[str] = None, data: Optional[dict] = None) -> None:
    """Never raises: a lost UI event must not break a journey."""
    try:
        with Session(engine) as s:
            s.add(Event(type=type, merchant_id=merchant_id, data=json.loads(json.dumps(data or {}, default=str))))
            s.commit()
    except Exception:  # noqa: BLE001
        log.exception("failed to publish event %s", type)
