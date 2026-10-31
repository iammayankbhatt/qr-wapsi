"""Field-visit (CPV) scheduling. Booking a visit never completes it: only a field employee can do that."""
from datetime import datetime
from typing import Optional

from sqlmodel import Session, select

from .. import audit, clock
from ..db import engine
from ..events import publish
from ..models import Employee, Merchant, Visit
from ..scheduling import next_quiet_slot, nearest_employee, quiet_hour


def find_visit_slot(merchant_id: str, after: Optional[str] = None) -> dict:
    """Next visit slot in the shop's quiet open hour (from payment timestamps), after the simulated clock or `after`."""
    with Session(engine) as s:
        m = s.get(Merchant, merchant_id)
        if m is None:
            raise KeyError(f"merchant {merchant_id} not found")
        start = datetime.fromisoformat(after) if after else clock.now()
        slot = next_quiet_slot(m, start)
    if slot is None:
        return {"found": False, "slot": None, "reason": "shop hours never overlap field hours"}
    return {"found": True, "slot": slot.isoformat(), "quiet_hour": quiet_hour(m, slot.date()),
            "reason": f"quietest open hour on {slot:%A} is {slot:%H}:00 (fewest payments)"}


def _route(s: Session, employee_id: str, day) -> list[Visit]:
    """That employee's open visits for the day, renumbered in time order."""
    visits = [v for v in s.exec(select(Visit).where(Visit.employee_id == employee_id).order_by(Visit.scheduled_at))
              if v.scheduled_at.date() == day]
    for i, v in enumerate(visits, start=1):
        v.route_order = i
        s.add(v)
    return visits


def book_visit(merchant_id: str, slot: str, employee_id: Optional[str] = None) -> dict:
    """Book the in-person check (CPV) and add it to the field employee's route for that day.
    Defaults to the employee whose base is nearest the shop. Re-booking returns the existing open visit."""
    at = datetime.fromisoformat(slot)
    with Session(engine) as s:
        m = s.get(Merchant, merchant_id)
        if m is None:
            raise KeyError(f"merchant {merchant_id} not found")
        visit = s.exec(select(Visit).where(Visit.merchant_id == merchant_id, Visit.completed_at == None)).first()  # noqa: E711
        new = visit is None
        if new:
            emp = s.get(Employee, employee_id) if employee_id else nearest_employee(m, s.exec(select(Employee)).all())
            if emp is None:
                return {"ok": False, "error": f"no field employee {employee_id or ''}".strip()}
            visit = Visit(merchant_id=merchant_id, employee_id=emp.id, scheduled_at=at)
            s.add(visit)
            s.flush()
        route = _route(s, visit.employee_id, visit.scheduled_at.date())
        s.commit()
        s.refresh(visit)
        emp = s.get(Employee, visit.employee_id)
        out = {"ok": True, "visit_id": visit.id, "employee_id": emp.id, "employee_name": emp.name,
               "scheduled_at": visit.scheduled_at.isoformat(), "route_order": visit.route_order,
               "route": [{"visit_id": v.id, "merchant_id": v.merchant_id, "scheduled_at": v.scheduled_at.isoformat(),
                          "route_order": v.route_order} for v in route]}
    if new:
        audit.log(merchant_id, "agent", "VISIT_BOOKED", {k: out[k] for k in ("visit_id", "employee_id", "scheduled_at", "route_order")})
        publish("visit.booked", merchant_id, out)
    return out
