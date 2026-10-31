"""Field app API. Completing a visit is a human action by a field employee: it is the only way to satisfy CPV_DONE."""
import base64
from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from .. import audit, clock
from ..agent import service
from ..config import settings
from ..db import engine
from ..events import publish
from ..models import Employee, Merchant, Visit
from ..scheduling import distance_km
from .journeys import journey_view

router = APIRouter()

GEO_TOLERANCE_M = 250  # geo-tag must be taken at the shop


@router.get("/employees")
def list_employees():
    with Session(engine) as s:
        return {"employees": [e.model_dump() for e in s.exec(select(Employee).order_by(Employee.id))]}


@router.get("/visits")
def list_visits(employee_id: Optional[str] = None, day: Optional[date] = None):
    """A field employee's route: visits for one day (default: the simulated clock's day) in route order."""
    day = day or clock.now().date()
    with Session(engine) as s:
        q = select(Visit).order_by(Visit.employee_id, Visit.route_order, Visit.scheduled_at)
        if employee_id:
            q = q.where(Visit.employee_id == employee_id)
        out = []
        for v in s.exec(q):
            if v.scheduled_at.date() != day:
                continue
            m = s.get(Merchant, v.merchant_id)
            e = s.get(Employee, v.employee_id)
            out.append({**v.model_dump(mode="json"), "employee_name": e.name if e else None,
                        "shop_name": m.shop_name, "owner_name": m.owner_name, "locality": m.locality, "city": m.city,
                        "lat": m.lat, "lng": m.lng, "category": m.category})
    return {"day": day.isoformat(), "visits": out}


class CompleteVisit(BaseModel):
    employee_id: str
    lat: float
    lng: float
    signboard_photo: str  # data URL from the field app camera, or a stored file name
    confirmed: bool = True
    note: Optional[str] = None


def _store_photo(mid: str, visit_id: int, photo: str) -> str:
    if not photo.startswith("data:image"):
        return photo
    try:
        data = base64.b64decode(photo.split(",", 1)[1])
    except (IndexError, ValueError) as e:
        raise HTTPException(422, "signboard_photo is not a valid data URL") from e
    folder = settings.DATA_DIR / "uploads" / mid
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"signboard_visit{visit_id}.jpg"
    path.write_bytes(data)
    return str(path)


@router.post("/visits/{visit_id}/complete")
def complete_visit(visit_id: int, body: CompleteVisit):
    if not body.confirmed:
        raise HTTPException(422, "the field employee must confirm the in-person check")
    if not body.signboard_photo.strip():
        raise HTTPException(422, "a signboard photo is required")
    with Session(engine) as s:
        v = s.get(Visit, visit_id)
        if v is None:
            raise HTTPException(404, f"visit {visit_id} not found")
        if v.completed_at is not None:
            raise HTTPException(409, f"visit {visit_id} is already completed")
        emp = s.get(Employee, body.employee_id)
        if emp is None:
            raise HTTPException(403, f"{body.employee_id} is not a field employee")
        m = s.get(Merchant, v.merchant_id)
        dist_m = round(distance_km(body.lat, body.lng, m.lat, m.lng) * 1000)
        if dist_m > GEO_TOLERANCE_M:
            raise HTTPException(422, f"geo-tag is {dist_m} m from the shop (must be within {GEO_TOLERANCE_M} m)")
        v.geo_tag = {"lat": body.lat, "lng": body.lng, "distance_m": dist_m}
        v.signboard_photo = _store_photo(v.merchant_id, v.id, body.signboard_photo)
        emp_id, emp_name = emp.id, emp.name
        v.confirmed_by = emp_id
        v.completed_at = clock.now()
        s.add(v)
        s.commit()
        mid, completed_at = v.merchant_id, v.completed_at

    audit.log(mid, f"human:{emp_id}", "CPV_COMPLETED", {"visit_id": visit_id, "employee": emp_name,
                                                        "distance_m": dist_m, "note": body.note,
                                                        "completed_at": completed_at.isoformat()})
    publish("visit.completed", mid, {"visit_id": visit_id, "employee_id": emp_id, "distance_m": dist_m})

    event = {"type": "field_done", "visit_id": visit_id}
    waiting = (service.snapshot(mid)["waiting"] or {}).get("waiting_for")
    if waiting in ("field_employee", "shopkeeper"):  # shopkeeper: a document-collection visit on the last rung
        try:
            service.resume(mid, event, waiting)
        except service.JourneyConflict:
            pass
    return journey_view(mid)
