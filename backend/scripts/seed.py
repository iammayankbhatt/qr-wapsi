"""Synthetic data seed. Fixed random seed; idempotent (drops and recreates all tables).

Run:  python scripts/seed.py     (from backend/)
All names, shops and numbers are invented. Row 0 of each histogram is Monday.
"""
import shutil
import sqlite3
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlmodel import Session, SQLModel, select  # noqa: E402

from app.config import settings  # noqa: E402
from app.db import engine  # noqa: E402
from app.models import Employee, Journey, Merchant  # noqa: E402
from app.scoring import mule_risk_score, priority  # noqa: E402

SEED = 20251231
N_MERCHANTS = 1000
HERO_ID = "M0001"

# name, share, median monthly GMV, avg ticket, open-hour range, close-hour range, morning peak, evening peak, weekend factor
CATEGORIES = {
    "kirana": dict(share=0.28, gmv=140_000, ticket=140, open=(7, 9), close=(21, 23), m=9.5, e=19.0, wk=1.1),
    "chemist": dict(share=0.10, gmv=180_000, ticket=280, open=(8, 10), close=(21, 23), m=11.0, e=19.0, wk=0.95),
    "tea stall": dict(share=0.12, gmv=45_000, ticket=25, open=(6, 8), close=(19, 22), m=8.5, e=17.5, wk=1.05),
    "mobile repair": dict(share=0.10, gmv=70_000, ticket=450, open=(10, 11), close=(20, 22), m=12.0, e=18.5, wk=1.1),
    "tailor": dict(share=0.08, gmv=40_000, ticket=600, open=(9, 11), close=(19, 21), m=11.5, e=17.5, wk=0.9),
    "sweet shop": dict(share=0.08, gmv=120_000, ticket=220, open=(8, 10), close=(21, 23), m=10.5, e=19.0, wk=1.25),
    "vegetable vendor": dict(share=0.14, gmv=55_000, ticket=60, open=(6, 8), close=(19, 21), m=8.5, e=18.0, wk=1.15),
    "hardware": dict(share=0.10, gmv=160_000, ticket=520, open=(9, 10), close=(19, 21), m=11.0, e=17.0, wk=0.85),
}

SURNAMES = ["Sharma", "Verma", "Gupta", "Singh", "Yadav", "Tyagi", "Kumar", "Chauhan", "Mishra", "Pandey", "Joshi",
            "Bansal", "Agarwal", "Tiwari", "Saxena", "Rawat", "Negi", "Bhatia", "Malhotra", "Khanna", "Jain", "Rana",
            "Kashyap", "Dubey", "Goel", "Mittal", "Garg", "Chaudhary", "Solanki", "Bisht"]
FIRST_M = ["Suresh", "Mahesh", "Dinesh", "Rajesh", "Anil", "Sunil", "Vijay", "Manoj", "Sanjay", "Pradeep", "Rakesh",
           "Ashok", "Deepak", "Naveen", "Mukesh", "Yogesh", "Harish", "Lalit", "Pankaj", "Girish", "Ramesh", "Imran"]
FIRST_F = ["Kavita", "Sunita", "Anita", "Meena", "Rekha", "Seema", "Poonam", "Geeta", "Neeta", "Pooja", "Savita",
           "Sarita", "Usha", "Radha", "Babita"]
AUSPICIOUS = ["Shree Ganesh", "Balaji", "Jai Mata Di", "Laxmi", "Shiv Shakti", "Krishna", "Sai Kripa", "Om Sai",
              "Annapurna", "Maa Durga", "Gopal", "Nav Durga", "Bhole", "Hanuman", "Radhe"]

TEMPLATES = {
    "kirana": ["{S} Kirana Store", "{A} General Store", "New {S} Provision Store"],
    "chemist": ["{A} Medical Hall", "{S} Chemist", "{A} Medicos"],
    "tea stall": ["{S} Chai Point", "{S} Tea Stall", "{A} Chai Adda"],
    "mobile repair": ["{S} Mobile Repair", "{A} Mobile Care", "Mobile Doctor {S}"],
    "tailor": ["{S} Tailors", "New {A} Tailoring", "{S} Ladies Tailor"],
    "sweet shop": ["{S} Mithai Wala", "{A} Sweets", "{S} Sweet House"],
    "vegetable vendor": ["{S} Sabzi Bhandar", "Fresh Sabzi {S}", "{A} Fruit & Veg"],
    "hardware": ["{S} Hardware & Paints", "{A} Hardware Store", "{S} Sanitary & Hardware"],
}

# (locality, city, lat, lng): centres inside lat 28.45-28.70, lng 77.20-77.45
LOCALITIES = [
    ("Sector 62", "Noida", 28.6270, 77.3650), ("Sector 18", "Noida", 28.5700, 77.3210),
    ("Sector 15", "Noida", 28.5850, 77.3120), ("Sector 50", "Noida", 28.5700, 77.3600),
    ("Sector 27", "Noida", 28.5880, 77.3340), ("Sector 76", "Noida", 28.5630, 77.3800),
    ("Sector 137", "Noida", 28.5030, 77.4080), ("Sector 63", "Noida", 28.6200, 77.3770),
    ("Sector 93", "Noida", 28.5420, 77.3990), ("Sector 41", "Noida", 28.5640, 77.3420),
    ("Mayur Vihar", "Delhi NCR", 28.6080, 77.2970), ("Patparganj", "Delhi NCR", 28.6250, 77.2930),
    ("Preet Vihar", "Delhi NCR", 28.6410, 77.2950), ("Laxmi Nagar", "Delhi NCR", 28.6300, 77.2770),
    ("Vasundhara", "Delhi NCR", 28.6600, 77.3600), ("Indirapuram", "Delhi NCR", 28.6400, 77.3700),
    ("Sarita Vihar", "Delhi NCR", 28.5300, 77.2900), ("Okhla", "Delhi NCR", 28.5400, 77.2700),
    ("Kalkaji", "Delhi NCR", 28.5500, 77.2500), ("Badarpur", "Delhi NCR", 28.4900, 77.3000),
]

EMPLOYEES = [
    ("E01", "Rohit Chauhan", "Sector 15, Noida", 28.5850, 77.3120),
    ("E02", "Priya Nagar", "Sector 18, Noida", 28.5700, 77.3210),
    ("E03", "Sandeep Yadav", "Sector 50, Noida", 28.5700, 77.3600),
    ("E04", "Neha Tyagi", "Sector 62, Noida", 28.6270, 77.3650),
    ("E05", "Imran Qureshi", "Sector 76, Noida", 28.5630, 77.3800),
    ("E06", "Vikram Rawat", "Sector 27, Noida", 28.5880, 77.3340),
]


def hour_weights(p: dict, open_h: int, close_h: int, dip: float) -> np.ndarray:
    """Morning + evening peaks, afternoon lull around 15:00, zero outside open hours."""
    h = np.arange(24)
    w = (0.9 * np.exp(-((h - p["m"]) ** 2) / (2 * 1.6**2))
         + 1.0 * np.exp(-((h - p["e"]) ** 2) / (2 * 1.8**2))
         + 0.25)
    w = w * (1 - dip * np.exp(-((h - 15) ** 2) / (2 * 1.0**2)))
    w[(h < open_h) | (h >= close_h)] = 0
    return w


def build_histogram(rng, p, open_h, close_h, dip, weekly_txns, *, hero=False, mule=False, night_share=0.0):
    w = hour_weights(p, open_h, close_h, dip)
    day_mult = np.array([1, 1, 1, 1, 1, p["wk"], p["wk"]], dtype=float)
    expected = np.outer(day_mult, w)
    expected = expected / expected.sum() * weekly_txns
    if hero:
        # near-deterministic so the lull at 15:00 is unmistakably the quietest open hour
        counts = np.rint(expected).astype(int)
        jitter = rng.integers(-1, 2, size=counts.shape)
        jitter[:, 15] = 0
        counts = np.where(expected > 8, counts + jitter, counts)
        # 15:00 must be strictly the quietest open hour on every day of the week
        for hr in range(open_h, close_h):
            if hr != 15:
                counts[:, hr] = np.maximum(counts[:, hr], counts[:, 15] + 1)
    else:
        counts = rng.poisson(expected * rng.lognormal(0, 0.1, size=(7, 1)))
    if mule:
        counts[int(rng.integers(0, 7))] *= 4  # one-day burst
        night_total = night_share / (1 - night_share) * counts.sum()
        counts[:, 0:5] += rng.poisson(night_total / 35, size=(7, 5))
    return counts.astype(int)


def risk_from_histogram(hist: np.ndarray) -> tuple[float, float]:
    daily = hist.sum(axis=1)
    spike = float(daily.max() / daily.mean()) if daily.mean() else 1.0
    night = float(hist[:, 0:6].sum() / hist.sum()) if hist.sum() else 0.0
    return round(spike, 3), round(night, 3)


def make_name(rng, cat: str) -> tuple[str, str]:
    while True:
        female = rng.random() < 0.15
        first = str(rng.choice(FIRST_F if female else FIRST_M))
        sur = str(rng.choice(SURNAMES))
        shop = str(rng.choice(TEMPLATES[cat])).format(S=sur, A=str(rng.choice(AUSPICIOUS)))
        owner = f"{first} {sur}"
        if shop != "Sharma Kirana Store" and owner != "Ramesh Sharma":
            return shop, owner


def generate() -> tuple[list[Merchant], list[Employee]]:
    rng = np.random.default_rng(SEED)
    rng_loan = np.random.default_rng(SEED + 1)  # separate stream so loan/pause fields don't shift the rest
    today = date.today()
    n = N_MERCHANTS
    others = rng.permutation(np.arange(1, n))  # indices 1..n-1 (0 is the hero)

    def pick(count):  # exact-count random subset, never the hero
        return set(rng.permutation(others)[:count].tolist())

    ckycr = pick(round(0.30 * n))
    big = pick(round(0.08 * n))
    mules = set(rng.permutation([i for i in others.tolist() if i not in big])[: round(0.03 * n)].tolist())
    no_soundbox = pick(n - round(0.85 * n))
    loan = pick(round(0.20 * n) - 1)  # hero is the +1
    doc_order = rng.permutation(others).tolist()  # disjoint doc-status groups: 70% / 15% / 15%
    missing_both = set(doc_order[: round(0.70 * n)])
    missing_one = set(doc_order[round(0.70 * n): round(0.85 * n)])

    cats = list(CATEGORIES)
    cat_idx = rng.choice(len(cats), size=n, p=[CATEGORIES[c]["share"] for c in cats])

    merchants: list[Merchant] = []
    for i in range(n):
        mid = f"M{i + 1:04d}"
        hero = i == 0
        cat = "kirana" if hero else cats[int(cat_idx[i])]
        p = CATEGORIES[cat]
        is_big, is_mule = i in big, i in mules

        if hero:
            shop, owner = "Sharma Kirana Store", "Ramesh Sharma"
            loc = LOCALITIES[0]
            lat, lng = 28.6270, 77.3650
            gmv, open_h, close_h, dip = 320_000, 8, 22, 0.8
        else:
            shop, owner = make_name(rng, cat)
            loc = LOCALITIES[int(rng.integers(0, len(LOCALITIES)))]
            lat = float(np.clip(loc[2] + rng.normal(0, 0.004), 28.45, 28.70))
            lng = float(np.clip(loc[3] + rng.normal(0, 0.004), 77.20, 77.45))
            if is_big:
                gmv = float(rng.uniform(360_000, 900_000))
            else:
                gmv = float(p["gmv"] * rng.lognormal(0, 0.45))
                if gmv > 280_000:  # keep small merchants below the hero without piling up on a hard cap
                    gmv = float(rng.uniform(190_000, 280_000))
                gmv = max(gmv, 12_000)
            open_h = int(rng.integers(p["open"][0], p["open"][1] + 1))
            close_h = int(rng.integers(p["close"][0], p["close"][1] + 1))
            dip = float(rng.uniform(0.5, 0.75))
        gmv = round(gmv, -2)

        annual = gmv * 12
        band = "UP_TO_10L" if annual <= 1_000_000 else "10L_TO_40L" if annual <= 4_000_000 else "ABOVE_40L"
        has_soundbox = hero or i not in no_soundbox

        night_target = float(rng.uniform(0.25, 0.40)) if is_mule else 0.0
        hist = build_histogram(rng, p, open_h, close_h, dip, gmv / p["ticket"] / 4.345,
                               hero=hero, mule=is_mule, night_share=night_target)
        spike, night = risk_from_histogram(hist)
        if hero:
            diversity, round_share = 0.91, 0.14
        elif is_mule:
            diversity, round_share = float(rng.uniform(0.04, 0.22)), float(rng.uniform(0.65, 0.95))
        else:
            diversity, round_share = float(rng.uniform(0.55, 0.95)), float(rng.uniform(0.08, 0.40))

        if hero or i in missing_both:
            pan, ovd = "MISSING", "MISSING"
        elif i in missing_one:
            pan, ovd = ("MISSING", "COLLECTED") if i % 2 else ("COLLECTED", "MISSING")
        else:
            pan, ovd = "COLLECTED", "COLLECTED"  # on file but not yet verified

        has_loan = hero or (i in loan)
        loan_ratio, days_paused = float(rng_loan.uniform(0.15, 0.55)), int(rng_loan.integers(1, 51))
        loan_outstanding = 120_000.0 if hero else (round(gmv * loan_ratio, -3) if has_loan else 0.0)
        if hero:
            days_paused = 55  # paused the longest, one of the tuned reasons it tops the queue

        merchants.append(Merchant(
            id=mid, shop_name=shop, owner_name=owner, category=cat, city=loc[1], locality=loc[0],
            lat=round(lat, 6), lng=round(lng, 6), turnover_band=band,
            in_ckycr=(i in ckycr), qr_status="PAUSED", has_soundbox=has_soundbox,
            monthly_gmv=gmv, subscription_per_month=90.0 if has_soundbox else 0.0,
            has_active_loan=has_loan, loan_outstanding=loan_outstanding,
            paused_since=datetime.combine(today - timedelta(days=days_paused), time.min),
            hourly_txn_histogram=hist.tolist(),
            open_hours={"open_hour": open_h, "close_hour": close_h},
            risk_features={"payer_diversity": round(diversity, 3), "spike_ratio": spike,
                           "round_amount_share": round(round_share, 3), "night_share": night},
            docs_status={"PAN": pan, "FORM60": "MISSING", "OVD": ovd},
        ))

    employees = [Employee(id=e[0], name=e[1], home_base=e[2], home_lat=e[3], home_lng=e[4]) for e in EMPLOYEES]
    return merchants, employees


def seed_all() -> dict:
    SQLModel.metadata.drop_all(engine)
    SQLModel.metadata.create_all(engine)
    merchants, employees = generate()
    with Session(engine) as s:
        s.add_all(employees)
        for m in merchants:
            s.add(m)
            pr = priority(m)
            s.add(Journey(merchant_id=m.id, current_step="TRIAGE", priority_score=pr.score,
                          priority_reasons=pr.reasons, mule_risk_score=mule_risk_score(m.risk_features),
                          attempts={}))
        s.commit()
    return {"merchants": len(merchants), "employees": len(employees)}


def reset_all() -> dict:
    """Full demo reset: reseed (this also empties audit log, review cases, documents, visits),
    clear uploads and LangGraph checkpoints."""
    counts = seed_all()
    uploads = settings.DATA_DIR / "uploads"
    shutil.rmtree(uploads, ignore_errors=True)
    uploads.mkdir(parents=True, exist_ok=True)

    cp = settings.checkpoint_path
    if cp.exists():
        try:
            con = sqlite3.connect(cp)
            for (t,) in con.execute("select name from sqlite_master where type='table' and name not like 'sqlite_%'").fetchall():
                con.execute(f'delete from "{t}"')
            con.commit()
            con.close()
        except sqlite3.Error:
            cp.unlink(missing_ok=True)
    return counts


if __name__ == "__main__":
    from collections import Counter

    print("seeded:", reset_all())
    with Session(engine) as s:
        ms = s.exec(select(Merchant)).all()
        js = {j.merchant_id: j for j in s.exec(select(Journey)).all()}
    print("\nmerchants per category:")
    for c, k in sorted(Counter(m.category for m in ms).items(), key=lambda x: -x[1]):
        print(f"  {c:18s}{k:5d}")
    print("\nqr_status:", dict(Counter(m.qr_status for m in ms)))
    print("turnover_band:", dict(Counter(m.turnover_band for m in ms)))
    print("in_ckycr:", sum(m.in_ckycr for m in ms), "| soundbox:", sum(m.has_soundbox for m in ms),
          "| loan:", sum(m.has_active_loan for m in ms),
          "| mule-like (score>=0.5):", sum(js[m.id].mule_risk_score >= 0.5 for m in ms))
    print("city:", dict(Counter(m.city for m in ms)))
    print("lat range:", min(m.lat for m in ms), max(m.lat for m in ms),
          "| lng range:", min(m.lng for m in ms), max(m.lng for m in ms))
