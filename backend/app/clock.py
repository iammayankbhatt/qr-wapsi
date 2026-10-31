"""Simulated wall clock (naive local IST) used for retry delays and visit booking.

Shared by the API process and the MCP tool process through the SimClock table. After a demo reset it
reads today 10:30 (start of the field day), so the hero's 15:10 quiet-hour visit is always later today.
The /demo "+2 hours" button calls advance(2).
"""
from datetime import date, datetime, time, timedelta

from sqlmodel import Session

from .db import engine
from .models import SimClock

DAY_START = time(10, 30)


def _row(s: Session) -> SimClock:
    row = s.get(SimClock, 1)
    if row is None:
        row = SimClock(id=1, now=datetime.combine(date.today(), DAY_START))
        s.add(row)
        s.commit()
        s.refresh(row)
    return row


def now() -> datetime:
    with Session(engine) as s:
        return _row(s).now


def advance(hours: float) -> datetime:
    with Session(engine) as s:
        row = _row(s)
        row.now = row.now + timedelta(hours=hours)
        s.add(row)
        s.commit()
        return row.now


def reset() -> datetime:
    with Session(engine) as s:
        row = _row(s)
        row.now = datetime.combine(date.today(), DAY_START)
        s.add(row)
        s.commit()
        return row.now
