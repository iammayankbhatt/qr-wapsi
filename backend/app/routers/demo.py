from fastapi import APIRouter
from pydantic import BaseModel, Field

from .. import clock
from ..agent import service
from ..events import publish
from scripts.seed import reset_all

router = APIRouter()


@router.post("/reset")
def reset():
    """Reseed merchants and clear audit log, review cases, documents, visits, chat, uploads and agent checkpoints;
    the simulated clock goes back to today 10:30."""
    counts = reset_all()
    now = clock.reset()
    publish("demo.reset", None, {"clock": now.isoformat()})
    return {"status": "ok", **counts, "clock": now.isoformat()}


@router.get("/clock")
def get_clock():
    return {"now": clock.now().isoformat()}


class Advance(BaseModel):
    hours: float = Field(2, gt=0, le=48)


@router.post("/advance-clock")
def advance_clock(body: Advance = Advance()):
    """The "+2 hours" button: move the simulated clock, then let every waiting journey run its retry ladder."""
    now = clock.advance(body.hours)
    publish("clock.advanced", None, {"now": now.isoformat(), "hours": body.hours})
    return {"now": now.isoformat(), "resumed": service.tick_all()}
