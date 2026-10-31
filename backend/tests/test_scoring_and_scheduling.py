from datetime import date, datetime

from fastapi.testclient import TestClient
from sqlmodel import select

from app.main import app
from app.models import Merchant
from app.scheduling import find_quiet_slot, quiet_hour
from app.scoring import MULE_REVIEW_THRESHOLD, mule_risk, mule_risk_score, priority
from tests.conftest import make_merchant

NOW = datetime(2026, 11, 1)
MULE = {"payer_diversity": 0.05, "spike_ratio": 5, "round_amount_share": 0.9, "night_share": 0.4}


def ranked(session):
    ms = session.exec(select(Merchant)).all()
    return sorted(ms, key=lambda m: (-priority(m, NOW).score, m.id))


# ---- scoring ----

def test_hero_is_ranked_first(session):
    r = ranked(session)
    assert r[0].id == "M0001"
    assert priority(r[0], NOW).score - priority(r[1], NOW).score > 3  # a real margin, not a coin-flip


def test_top_three_reasons_are_structured(session):
    p = priority(session.get(Merchant, "M0001"), NOW)
    assert len(p.reasons) == 3
    assert all(set(r) == {"label", "detail"} and r["label"] and r["detail"] for r in p.reasons)


def test_active_loan_reason_shows_outstanding(session):
    m = make_merchant(session, "T_LOAN", has_active_loan=True, loan_outstanding=120_000, monthly_gmv=1000,
                      has_soundbox=False, docs_status={"PAN": "OK", "OVD": "OK"})
    assert {"label": "Active loan", "detail": "₹1.2L outstanding"} in priority(m, NOW).reasons


def test_value_at_risk_document_gap_and_days_paused_raise_priority(session):
    base = dict(docs_status={"PAN": "OK", "FORM60": "MISSING", "OVD": "OK"}, paused_since=NOW, monthly_gmv=100_000)
    lo = priority(make_merchant(session, "T_A", **base), NOW).score
    variants = {
        "gmv": {"monthly_gmv": 250_000},
        "loan": {"has_active_loan": True, "loan_outstanding": 100_000},
        "soundbox": {"has_soundbox": True, "subscription_per_month": 90},
        "doc gap": {"docs_status": {"PAN": "MISSING", "OVD": "MISSING"}},
        "days paused": {"paused_since": datetime(2026, 9, 1)},
    }
    for i, (name, change) in enumerate(variants.items()):
        score = priority(make_merchant(session, f"T_V{i}", **{**base, **change}), NOW).score
        assert score > lo, name


def test_mule_merchant_has_high_risk_with_top_features(session):
    mules = [m for m in session.exec(select(Merchant)).all()
             if m.id.startswith("M") and mule_risk_score(m.risk_features) >= MULE_REVIEW_THRESHOLD]
    assert len(mules) == 30
    risk = mule_risk(mules[0].risk_features)
    assert risk["flagged"] and risk["score"] >= 0.7
    assert 1 <= len(risk["top_features"]) <= 3
    assert all({"feature", "label", "detail", "contribution"} <= set(f) for f in risk["top_features"])
    assert risk["top_features"][0]["contribution"] >= risk["top_features"][-1]["contribution"]


def test_hero_is_low_risk_and_empty_features_are_safe(session):
    hero = mule_risk(session.get(Merchant, "M0001").risk_features)
    assert hero["score"] < 0.2 and hero["top_features"] == []  # nothing worth flagging
    assert 0 <= mule_risk_score({}) <= 1


def test_mule_and_full_cdd_merchants_rank_below_clean_peers(session):
    clean = dict(has_soundbox=True, subscription_per_month=90, monthly_gmv=200_000, paused_since=NOW)
    ok = priority(make_merchant(session, "T_OK", **clean), NOW).score
    mule = priority(make_merchant(session, "T_MU", **clean, risk_features=MULE), NOW).score
    big = priority(make_merchant(session, "T_BG", **clean, turnover_band="ABOVE_40L"), NOW).score
    assert mule < ok and big < ok


def test_queue_endpoint(session):
    with TestClient(app) as client:
        r = client.get("/api/queue", params={"limit": 5})
    assert r.status_code == 200
    body = r.json()
    assert len(body["items"]) == 5
    assert body["items"][0]["merchant_id"] == "M0001" and body["items"][0]["rank"] == 1
    scores = [i["priority_score"] for i in body["items"]]
    assert scores == sorted(scores, reverse=True)
    assert len(body["items"][0]["reasons"]) == 3 and "score" in body["items"][0]["mule_risk"]


# ---- quiet slot ----

def test_hero_quiet_slot_is_3_10_pm_every_day(session):
    hero = session.get(Merchant, "M0001")
    for offset in range(7):
        assert find_quiet_slot(hero, date(2026, 11, 2 + offset)) == datetime(2026, 11, 2 + offset, 15, 10)


def test_slot_stays_inside_field_hours_even_if_shop_is_quietest_outside(session):
    hist = [[5] * 24 for _ in range(7)]
    for d in range(7):
        hist[d][8] = 0    # quietest hour overall is 08:00, before field hours
        hist[d][19] = 0   # and 19:00, after them
        hist[d][13] = 1   # best hour inside 10-18
    m = make_merchant(session, "T_Q", hourly_txn_histogram=hist, open_hours={"open_hour": 8, "close_hour": 21})
    assert find_quiet_slot(m, date(2026, 11, 2)) == datetime(2026, 11, 2, 13, 10)


def test_slot_stays_inside_open_hours(session):
    hist = [[9 if 14 <= h < 17 else 0 for h in range(24)] for _ in range(7)]  # zero traffic when shut
    m = make_merchant(session, "T_Q2", hourly_txn_histogram=hist, open_hours={"open_hour": 14, "close_hour": 17})
    assert quiet_hour(m, date(2026, 11, 2)) in (14, 15, 16)


def test_no_slot_when_open_hours_miss_field_hours(session):
    m = make_merchant(session, "T_Q3", open_hours={"open_hour": 6, "close_hour": 10})
    assert find_quiet_slot(m, date(2026, 11, 2)) is None


def test_uses_the_weekday_of_the_requested_date(session):
    hist = [[4] * 24 for _ in range(7)]
    hist[0][11] = 0   # Monday: 11:00 quietest
    hist[1][16] = 0   # Tuesday: 16:00 quietest
    m = make_merchant(session, "T_Q4", hourly_txn_histogram=hist)
    assert find_quiet_slot(m, date(2026, 11, 2)).hour == 11   # Monday
    assert find_quiet_slot(m, date(2026, 11, 3)).hour == 16   # Tuesday
