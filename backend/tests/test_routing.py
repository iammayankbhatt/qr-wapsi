"""OR-Tools day route: time windows around quiet hours, service time, straight-line travel."""
from datetime import date, datetime

from app.scheduling import SERVICE_MIN, WINDOW_MIN, Stop, solve_route, travel_min
from scripts.seed import prebooked_visits

DAY = date(2026, 11, 2)
HOME = (28.6270, 77.3650)


def at(h, m=10):
    return datetime(2026, 11, 2, h, m)


def test_travel_time_is_straight_line_at_18_kmph():
    assert travel_min(28.6270, 77.3650, 28.6270, 77.3650) == 0
    assert 9 <= travel_min(28.6270, 77.3650, 28.6540, 77.3650) <= 11  # ~3 km


def test_stops_are_ordered_and_land_on_their_slots():
    stops = [Stop(1, 28.640, 77.370, at(15)), Stop(2, 28.620, 77.380, at(11)), Stop(3, 28.630, 77.350, at(13))]
    plan = solve_route(HOME, stops, DAY)
    assert plan["status"] == "optimal"
    assert [o["key"] for o in plan["order"]] == [2, 3, 1]
    assert [o["eta"] for o in plan["order"]] == [at(11), at(13), at(15)]
    assert all((o["depart"] - o["eta"]).seconds == SERVICE_MIN * 60 for o in plan["order"])


def test_etas_stay_inside_the_window_when_slots_clash():
    stops = [Stop(1, 28.640, 77.370, at(15)), Stop(2, 28.600, 77.330, at(15, 20))]  # cannot both be on time
    plan = solve_route(HOME, stops, DAY)
    assert plan["status"] == "optimal"
    for o, s in zip(plan["order"], sorted(stops, key=lambda s: [x["key"] for x in plan["order"]].index(s.key))):
        assert abs((o["eta"] - s.slot).total_seconds()) <= WINDOW_MIN * 60
    first, second = plan["order"]
    assert second["eta"] >= first["depart"]  # service time and travel respected


def test_impossible_windows_fall_back_to_a_relaxed_plan():
    stops = [Stop(i, 28.60 + i * 0.03, 77.30, at(15)) for i in range(4)]  # four far-apart shops, same slot
    plan = solve_route(HOME, stops, DAY)
    assert plan["status"] == "relaxed" and len(plan["order"]) == 4


def test_seeded_days_leave_the_hero_hour_free(session):
    from sqlmodel import select

    from app.models import Employee, Merchant
    merchants, employees = session.exec(select(Merchant)).all(), session.exec(select(Employee)).all()
    visits = prebooked_visits(merchants, employees, DAY)
    assert len(visits) == 18 and "M0001" not in {v.merchant_id for v in visits}
    assert all(v.scheduled_at.hour != 15 for v in visits if v.employee_id == "E04")
    per_emp = {}
    for v in visits:
        per_emp.setdefault(v.employee_id, []).append(v.scheduled_at.hour)
    assert all(len(h) == len(set(h)) for h in per_emp.values())  # one visit per hour
