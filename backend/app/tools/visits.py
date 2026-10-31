"""Field-visit (CPV) scheduling. Booking a visit never completes it: only a field employee can do that."""
from datetime import datetime
from typing import Optional

from sqlmodel import Session, select

from .. import audit, clock
from ..db import engine
from ..events import publish
from ..models import Employee, Merchant, Visit
from ..scheduling import nearest_employee, next_quiet_slot, plan_route, quiet_hour


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


def book_visit(merchant_id: str, slot: str, employee_id: Optional[str] = None) -> dict:
    """Book the in-person check (CPV) and re-plan the field employee's day route with OR-Tools.
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
        s.commit()
        s.refresh(visit)
        visit_id, emp_id, day = visit.id, visit.employee_id, visit.scheduled_at.date()
    plan = plan_route(emp_id, day, persist=True)  # OR-Tools orders the whole day and gives ETAs
    me = next(x for x in plan["stops"] if x["visit_id"] == visit_id)
    out = {"ok": True, "visit_id": visit_id, "employee_id": emp_id, "employee_name": plan["employee_name"],
           "scheduled_at": me["slot"], "eta": me["eta"], "route_order": me["order"], "route_status": plan["status"],
           "route": [{k: x[k] for k in ("visit_id", "merchant_id", "eta", "order")} for x in plan["stops"]]}
    if new:
        audit.log(merchant_id, "agent", "VISIT_BOOKED", {k: out[k] for k in ("visit_id", "employee_id", "scheduled_at", "eta",
                                                                          "route_order", "route_status")})
        publish("visit.booked", merchant_id, out)
    return out
