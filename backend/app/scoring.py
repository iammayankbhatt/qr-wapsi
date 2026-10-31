"""Deterministic priority and mule-risk scores. No LLM: the LLM only explains the ranking.

Priority (0-100, higher = clear sooner) is a weighted sum of value at risk (Soundbox subscription,
GMV-linked revenue, active-loan exposure), document gap and days paused. Mule-risk signals pull a
merchant down the queue because those cases go to human review rather than the fast track.
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from .models import Merchant

MULE_REVIEW_THRESHOLD = 0.5  # at or above this the journey goes to human review

# Priority weights (points) and the value at which each earns its full weight.
W_SUBSCRIPTION, SUBSCRIPTION_CAP = 10, 90          # Rs / month
W_GMV_REVENUE, GMV_CAP = 35, 350_000               # Rs GMV / month
W_LOAN, LOAN_CAP = 15, 150_000                     # Rs outstanding
W_DOC_GAP = 15                                     # split evenly across the 2 required items
W_DAYS_PAUSED, DAYS_CAP = 15, 60
MULE_PENALTY, FULL_CDD_PENALTY = 40, 30
GMV_REVENUE_RATE = 0.004                           # assumed GMV-linked revenue share (illustrative)

TOP_FEATURE_MIN = 0.10
MULE_WEIGHTS = {"payer_diversity": 0.35, "spike_ratio": 0.20, "round_amount_share": 0.25, "night_share": 0.20}


def _lakh(x: float) -> str:
    return f"₹{x / 100000:.1f}L"


# ---------- mule risk ----------

def _mule_contributions(risk: dict) -> dict[str, float]:
    return {
        "payer_diversity": MULE_WEIGHTS["payer_diversity"] * (1 - risk.get("payer_diversity", 1.0)),
        "spike_ratio": MULE_WEIGHTS["spike_ratio"] * min(max(risk.get("spike_ratio", 1.0) - 1, 0) / 3, 1),
        "round_amount_share": MULE_WEIGHTS["round_amount_share"] * risk.get("round_amount_share", 0.0),
        "night_share": MULE_WEIGHTS["night_share"] * min(risk.get("night_share", 0.0) / 0.3, 1),
    }


def mule_risk_score(risk: dict) -> float:
    """0..1. Low payer diversity, day spikes, round amounts and night share all raise it."""
    return round(min(max(sum(_mule_contributions(risk).values()), 0.0), 1.0), 3)


def mule_risk(risk: dict) -> dict:
    """Score plus the top contributing features, human-readable."""
    contrib = _mule_contributions(risk)
    detail = {
        "payer_diversity": ("Low payer diversity", f"{risk.get('payer_diversity', 1):.2f} unique-payer ratio"),
        "spike_ratio": ("Day-level spikes", f"busiest day {risk.get('spike_ratio', 1):.1f}x the average"),
        "round_amount_share": ("Round-amount payments", f"{risk.get('round_amount_share', 0):.0%} of payments"),
        "night_share": ("Late-night activity", f"{risk.get('night_share', 0):.0%} of payments at 00:00–06:00"),
    }
    top = [
        {"feature": k, "label": detail[k][0], "detail": detail[k][1], "contribution": round(v, 3)}
        for k, v in sorted(contrib.items(), key=lambda kv: -kv[1])[:3]
        if v >= TOP_FEATURE_MIN  # tiny contributions are noise, not risk drivers
    ]
    score = mule_risk_score(risk)
    return {"score": score, "flagged": score >= MULE_REVIEW_THRESHOLD, "top_features": top}


# ---------- priority ----------

def missing_docs(docs_status: dict) -> list[str]:
    pan_ok = docs_status.get("PAN") not in (None, "MISSING") or docs_status.get("FORM60") not in (None, "MISSING")
    missing = [] if pan_ok else ["PAN"]
    if docs_status.get("OVD") in (None, "MISSING"):
        missing.append("ID proof")
    return missing


@dataclass
class Priority:
    score: float
    reasons: list[dict] = field(default_factory=list)      # top 3: {"label", "detail"}
    components: dict[str, float] = field(default_factory=dict)  # points per factor, for transparency


def days_paused(m: Merchant, now: Optional[datetime] = None) -> int:
    if m.paused_since is None:
        return 0
    return max(((now or datetime.now()) - m.paused_since).days, 0)


def priority(m: Merchant, now: Optional[datetime] = None) -> Priority:
    comps: dict[str, tuple[float, str, str]] = {}  # key -> (points, label, detail)

    sub = m.subscription_per_month if m.has_soundbox else 0
    if sub:
        comps["subscription"] = (W_SUBSCRIPTION * min(sub / SUBSCRIPTION_CAP, 1), "Soundbox subscription",
                                 f"₹{sub:.0f}/month not being collected")
    revenue = m.monthly_gmv * GMV_REVENUE_RATE
    comps["gmv"] = (W_GMV_REVENUE * min(m.monthly_gmv / GMV_CAP, 1), "Revenue at risk",
                    f"{_lakh(m.monthly_gmv)} GMV/month · ~₹{revenue:,.0f} revenue/month")
    if m.has_active_loan:
        comps["loan"] = (W_LOAN * min(m.loan_outstanding / LOAN_CAP, 1), "Active loan",
                         f"{_lakh(m.loan_outstanding)} outstanding")
    missing = missing_docs(m.docs_status)
    if missing:
        comps["docs"] = (W_DOC_GAP * len(missing) / 2, "Document gap", "Missing: " + ", ".join(missing))
    days = days_paused(m, now)
    comps["days"] = (W_DAYS_PAUSED * min(days / DAYS_CAP, 1), "Days paused", f"{days} days without a live QR")

    score = sum(p for p, _, _ in comps.values())
    mule = mule_risk_score(m.risk_features)
    if mule >= MULE_REVIEW_THRESHOLD:
        score -= MULE_PENALTY * mule
    if m.turnover_band == "ABOVE_40L":
        score -= FULL_CDD_PENALTY

    top = sorted(comps.values(), key=lambda c: -c[0])[:3]
    return Priority(
        score=round(score, 2),
        reasons=[{"label": label, "detail": detail} for _, label, detail in top],
        components={k: round(v[0], 2) for k, v in comps.items()},
    )
