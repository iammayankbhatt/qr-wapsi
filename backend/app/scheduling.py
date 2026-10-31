"""Quiet-hour finder and visit assignment (OR-Tools day routing is added in a later step)."""
import math
from datetime import date, datetime, time, timedelta
from typing import Iterable, Optional

from .models import Employee, Merchant

FIELD_START_HOUR, FIELD_END_HOUR = 10, 18  # field employees work 10:00-18:00
SLOT_MINUTE = 10                           # visits start 10 minutes past the quiet hour
SEARCH_DAYS = 7


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


def nearest_employee(merchant: Merchant, employees: Iterable[Employee]) -> Optional[Employee]:
    return min(employees, key=lambda e: (distance_km(e.home_lat, e.home_lng, merchant.lat, merchant.lng), e.id), default=None)
