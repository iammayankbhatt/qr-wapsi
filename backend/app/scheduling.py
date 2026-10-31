"""Quiet-hour finder, visit assignment and one employee's day route (OR-Tools)."""
import logging
import math
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Iterable, Optional

from .models import Employee, Merchant

log = logging.getLogger("qrwapsi.scheduling")

FIELD_START_HOUR, FIELD_END_HOUR = 10, 18  # field employees work 10:00-18:00
SLOT_MINUTE = 10                           # visits start 10 minutes past the quiet hour
SEARCH_DAYS = 7

WINDOW_MIN = 40      # a visit may start up to 40 min either side of the shop's quiet-hour slot
SERVICE_MIN = 20     # time spent at each shop
SPEED_KMPH = 18      # city travel speed, applied to straight-line distance
SOLVER_TIME_LIMIT_S = 2
GLS_MIN_STOPS = 8
ON_TIME_PENALTY = 100  # cost per minute of arriving off the slot (soft bounds pull the ETA onto the slot)


def quiet_hour(merchant: Merchant, day: date) -> Optional[int]:
    """Lowest-traffic hour that is inside the shop's open hours and inside field hours.

    Uses that weekday's row of the 7x24 histogram (row 0 = Monday); ties go to the hour that is
    quieter across the whole week, then to the earlier hour.
    """
    open_h = merchant.open_hours.get("open_hour", 0)
    close_h = merchant.open_hours.get("close_hour", 24)
    hist = merchant.hourly_txn_histogram
    candidates = [h for h in range(max(open_h, FIELD_START_HOUR), min(close_h, FIELD_END_HOUR))]
    if not candidates or not hist:
        return None
    row = hist[day.weekday()]
    return min(candidates, key=lambda h: (row[h], sum(d[h] for d in hist), h))


def find_quiet_slot(merchant: Merchant, day: date) -> Optional[datetime]:
    """Start time (naive local, IST) for a visit on `day`, or None if open and field hours never overlap."""
    hour = quiet_hour(merchant, day)
    return None if hour is None else datetime.combine(day, time(hour, SLOT_MINUTE))


def next_quiet_slot(merchant: Merchant, after: datetime) -> Optional[datetime]:
    """First quiet-hour slot strictly after `after`, looking up to a week ahead."""
    for d in range(SEARCH_DAYS + 1):
        slot = find_quiet_slot(merchant, after.date() + timedelta(days=d))
        if slot is not None and slot > after:
            return slot
    return None


def distance_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle (haversine) distance."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lng2 - lng1) / 2) ** 2
    return 6371.0 * 2 * math.asin(math.sqrt(a))


def travel_min(lat1: float, lng1: float, lat2: float, lng2: float) -> int:
    return math.ceil(distance_km(lat1, lng1, lat2, lng2) / SPEED_KMPH * 60)


def nearest_employee(merchant: Merchant, employees: Iterable[Employee]) -> Optional[Employee]:
    return min(employees, key=lambda e: (distance_km(e.home_lat, e.home_lng, merchant.lat, merchant.lng), e.id), default=None)


# ------------------------------------------------------------ day route

@dataclass
class Stop:
    key: int          # caller's id (visit id)
    lat: float
    lng: float
    slot: datetime    # quiet-hour slot the visit was booked for


def _minutes(dt: datetime) -> int:
    return dt.hour * 60 + dt.minute


def solve_route(home: tuple[float, float], stops: list[Stop], day: date) -> dict:
    """Order one employee's stops with OR-Tools: single vehicle from and back to home, time windows of
    slot ± WINDOW_MIN, SERVICE_MIN at each shop, straight-line travel at SPEED_KMPH. Arrivals are pulled onto
    each slot (soft bounds), so a shop is visited at its quiet hour whenever the route allows it.

    -> {status: optimal | relaxed | time_order, order: [{key, eta, depart, travel_min, distance_km}], return_eta}
    """
    from ortools.constraint_solver import pywrapcp, routing_enums_pb2

    points = [home] + [(s.lat, s.lng) for s in stops]
    n = len(points)
    travel = [[travel_min(*a, *b) for b in points] for a in points]
    service = [0] + [SERVICE_MIN] * len(stops)

    def solve(windows: bool):
        mgr = pywrapcp.RoutingIndexManager(n, 1, 0)
        r = pywrapcp.RoutingModel(mgr)
        cb = r.RegisterTransitCallback(lambda i, j: travel[mgr.IndexToNode(i)][mgr.IndexToNode(j)] + service[mgr.IndexToNode(i)])
        r.SetArcCostEvaluatorOfAllVehicles(cb)
        r.AddDimension(cb, 24 * 60, 24 * 60, False, "time")
        t = r.GetDimensionOrDie("time")
        t.CumulVar(r.Start(0)).SetRange(FIELD_START_HOUR * 60, FIELD_START_HOUR * 60)
        if windows:
            t.CumulVar(r.End(0)).SetMax(FIELD_END_HOUR * 60 + 60)
        for node, s in enumerate(stops, start=1):
            i, target = mgr.NodeToIndex(node), _minutes(s.slot)
            if windows:
                t.CumulVar(i).SetRange(target - WINDOW_MIN, target + WINDOW_MIN)
            t.SetCumulVarSoftUpperBound(i, target, ON_TIME_PENALTY)
            t.SetCumulVarSoftLowerBound(i, target, ON_TIME_PENALTY)
        p = pywrapcp.DefaultRoutingSearchParameters()
        p.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
        if len(stops) > GLS_MIN_STOPS:  # guided local search always runs to its time limit: only worth it on long days
            p.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
        p.time_limit.FromSeconds(SOLVER_TIME_LIMIT_S)
        sol = r.SolveWithParameters(p)
        if sol is None:
            return None
        seq, i = [], r.Start(0)
        while not r.IsEnd(i):
            seq.append((mgr.IndexToNode(i), sol.Min(t.CumulVar(i))))
            i = sol.Value(r.NextVar(i))
        return seq, sol.Min(t.CumulVar(i))

    status = "optimal"
    result = solve(windows=True) if stops else ([(0, FIELD_START_HOUR * 60)], FIELD_START_HOUR * 60)
    if result is None:
        status = "relaxed"  # windows cannot all be met: keep the soft pull towards each slot, drop hard windows
        result = solve(windows=False)
    if result is None:  # pragma: no cover - the relaxed model always has a solution
        status = "time_order"
        t, seq = FIELD_START_HOUR * 60, [(0, FIELD_START_HOUR * 60)]
        prev = 0
        for node in sorted(range(1, n), key=lambda k: stops[k - 1].slot):
            t = max(t + service[prev] + travel[prev][node], _minutes(stops[node - 1].slot))
            seq.append((node, t))
            prev = node
        result = (seq, t + service[prev] + travel[prev][0])

    seq, end = result
    at = lambda m: datetime.combine(day, time()) + timedelta(minutes=m)  # noqa: E731
    order, prev = [], 0
    for node, eta in seq[1:]:
        s = stops[node - 1]
        order.append({"key": s.key, "eta": at(eta), "depart": at(eta + SERVICE_MIN), "travel_min": travel[prev][node],
                      "distance_km": round(distance_km(*points[prev], *points[node]), 2)})
        prev = node
    return {"status": status, "order": order, "return_eta": at(end),
            "return_km": round(distance_km(*points[prev], *home), 2), "return_travel_min": travel[prev][0]}


def plan_route(employee_id: str, day: date, persist: bool = False) -> dict:
    """One employee's visits on `day`, ordered by OR-Tools, with ETAs. persist=True saves the order to Visit.route_order."""
    from sqlmodel import Session, select

    from .db import engine
    from .models import Visit

    with Session(engine) as s:
        emp = s.get(Employee, employee_id)
        if emp is None:
            raise KeyError(f"employee {employee_id} not found")
        visits = [v for v in s.exec(select(Visit).where(Visit.employee_id == employee_id)) if v.scheduled_at.date() == day]
        merchants = {v.merchant_id: s.get(Merchant, v.merchant_id) for v in visits}
        plan = solve_route((emp.home_lat, emp.home_lng),
                           [Stop(v.id, merchants[v.merchant_id].lat, merchants[v.merchant_id].lng, v.scheduled_at) for v in visits],
                           day)
        by_id = {v.id: v for v in visits}
        stops = []
        for n, o in enumerate(plan["order"], start=1):
            v = by_id[o["key"]]
            m = merchants[v.merchant_id]
            if persist and v.route_order != n:
                v.route_order = n
                s.add(v)
            stops.append({
                "order": n, "visit_id": v.id, "merchant_id": m.id, "shop_name": m.shop_name, "locality": m.locality,
                "lat": m.lat, "lng": m.lng, "slot": v.scheduled_at.isoformat(),
                "window_start": (v.scheduled_at - timedelta(minutes=WINDOW_MIN)).isoformat(),
                "window_end": (v.scheduled_at + timedelta(minutes=WINDOW_MIN)).isoformat(),
                "eta": o["eta"].isoformat(), "depart": o["depart"].isoformat(), "travel_min": o["travel_min"],
                "distance_km": o["distance_km"], "completed": v.completed_at is not None,
            })
        if persist:
            s.commit()
        out = {
            "employee_id": emp.id, "employee_name": emp.name, "day": day.isoformat(), "solver": "OR-Tools",
            "status": plan["status"], "home": {"name": emp.home_base, "lat": emp.home_lat, "lng": emp.home_lng},
            "start": datetime.combine(day, time(FIELD_START_HOUR)).isoformat(), "stops": stops,
            "return_eta": plan["return_eta"].isoformat(),
            "total_km": round(sum(x["distance_km"] for x in stops) + plan["return_km"], 2),
            "total_travel_min": sum(x["travel_min"] for x in stops) + plan["return_travel_min"],
            "params": {"window_min": WINDOW_MIN, "service_min": SERVICE_MIN, "speed_kmph": SPEED_KMPH},
        }
    log.info("route %s %s: %d stops, %s, %.1f km", employee_id, day, len(stops), out["status"], out["total_km"])
    return out
