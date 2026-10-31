import os
import tempfile

# Must happen before anything imports app.config: tests never touch the real backend/data/app.db.
_TMP = tempfile.mkdtemp(prefix="qrwapsi_test_")
os.environ["DATA_DIR"] = _TMP
os.environ["DEMO_MODE"] = "replay"
os.environ["TOOL_TRANSPORT"] = "direct"  # tests/test_tool_transport.py exercises MCP explicitly
os.environ["SIM_LATENCY_MS"] = "0"

import pytest  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlmodel import Session  # noqa: E402

from app.db import engine  # noqa: E402
from app.models import Merchant  # noqa: E402
from scripts.seed import seed_all  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def seeded():
    seed_all()


@pytest.fixture
def session():
    with Session(engine) as s:
        yield s


@pytest.fixture(autouse=True)
def clean_runtime_tables():
    """Each test starts with no documents, visits, review cases or audit entries (raw SQL: audit is ORM-append-only)."""
    with engine.begin() as c:
        for t in ("document", "visit", "reviewcase", "auditentry", "chatmessage", "event"):
            c.execute(text(f"DELETE FROM {t}"))
    yield


def make_merchant(session: Session, mid: str, **kw) -> Merchant:
    base = dict(
        id=mid, shop_name="Test Store", owner_name="Ramesh Sharma", category="kirana", city="Noida",
        lat=28.6, lng=77.3, turnover_band="10L_TO_40L", in_ckycr=False, monthly_gmv=100_000,
        hourly_txn_histogram=[[0] * 24 for _ in range(7)], open_hours={"open_hour": 8, "close_hour": 22},
        risk_features={"payer_diversity": 0.9, "spike_ratio": 1.2, "round_amount_share": 0.1, "night_share": 0.0},
        docs_status={"PAN": "MISSING", "FORM60": "MISSING", "OVD": "MISSING"},
    )
    base.update(kw)
    m = session.get(Merchant, mid)
    if m:
        session.delete(m)
        session.commit()
    m = Merchant(**base)
    session.add(m)
    session.commit()
    return m
