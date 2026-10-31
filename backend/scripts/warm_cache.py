"""Fill backend/demo_cache/ so the finale runs offline with DEMO_MODE=replay.

Run (from backend/):
  python scripts/warm_cache.py            record the four fixed Soundbox clips for M0001 (needs SARVAM_API_KEY)
  python scripts/warm_cache.py --journey  also run the whole finale once in record mode through the API, which
                                          records every LLM answer and clip it uses (resets the demo database)
  python scripts/warm_cache.py --check    no network: report which fixed clips are cached
"""
import argparse
import os
import shutil
import sys
from datetime import date, datetime
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))
sys.stdout.reconfigure(encoding="utf-8")

parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument("--journey", action="store_true", help="also run the finale once in record mode (resets the demo)")
parser.add_argument("--check", action="store_true", help="only report what is cached; never calls an API")
args = parser.parse_args()
if not args.check:
    os.environ["DEMO_MODE"] = "record"  # must be set before app.config is imported
    os.environ.setdefault("TOOL_TRANSPORT", "direct")

import logging  # noqa: E402

from sqlmodel import Session  # noqa: E402

from app import clock, voice  # noqa: E402
from app.agent.messages import soundbox_line  # noqa: E402
from app.config import settings  # noqa: E402
from app.db import engine, init_db  # noqa: E402
from app.documents import FIXES  # noqa: E402
from app.models import Merchant  # noqa: E402
from app.scheduling import next_quiet_slot  # noqa: E402

HERO = "M0001"
ASSETS = BACKEND / "demo_assets"


def fixed_lines() -> list[tuple[str, str]]:
    """The exact Soundbox lines the finale speaks for M0001 (same helper the agent uses)."""
    init_db()
    with Session(engine) as s:
        hero = s.get(Merchant, HERO)
    if hero is None:
        sys.exit("M0001 not found: run `python scripts/seed.py` first")
    day_start = datetime.combine(date.today(), clock.DAY_START)
    slot = next_quiet_slot(hero, day_start)
    return [
        ("first outreach", soundbox_line("OUTREACH")),
        ("document fix (blurry PAN)", soundbox_line("DOCUMENT_FIX", fix_hi=FIXES["BLURRY"][1])),
        ("visit booked", soundbox_line("VISIT_BOOKED", time=slot.strftime("%H:%M"))),
        ("QR live", soundbox_line("QR_LIVE")),
    ]


def record_clips() -> int:
    failures = 0
    for name, text in fixed_lines():
        key = voice.synthesize(text)
        failures += key is None
        print(f"  {'OK  ' if key else 'FAIL'} {name:28s} {key[:16] + '…' if key else '-':18s} {text}")
    return failures


def check_clips() -> int:
    missing = 0
    for name, text in fixed_lines():
        p = settings.DEMO_CACHE_DIR / "audio" / f"{voice.audio_key(text)}.wav"
        missing += not p.is_file()
        print(f"  {'cached ' if p.is_file() else 'MISSING'} {name:28s} {text}")
    n_llm = len(list((settings.DEMO_CACHE_DIR / 'llm').glob('*.json')))
    print(f"  LLM cache entries: {n_llm}")
    return missing


def run_journey() -> None:
    """The finale through the HTTP API in record mode: every LLM call and Soundbox clip lands in demo_cache/."""
    from fastapi.testclient import TestClient

    from app.main import app

    def upload(c, name, doc_type):
        with open(ASSETS / name, "rb") as f:
            r = c.post(f"/api/journeys/{HERO}/upload", files={"file": (name, f, "image/jpeg")}, data={"doc_type": doc_type})
        r.raise_for_status()
        print(f"  upload {name}: {r.json()['state']['last_check']['decision']}")

    with TestClient(app) as c:
        c.post("/api/demo/reset").raise_for_status()
        c.post(f"/api/journeys/{HERO}/start").raise_for_status()
        upload(c, "pan_blurry.jpg", "PAN")
        upload(c, "pan_sharp.jpg", "PAN")
        upload(c, "ovd_sharp.jpg", "OVD")
        visit = next(v for v in c.get("/api/field/visits").json()["visits"] if v["merchant_id"] == HERO)
        sign = "data:image/jpeg;base64," + __import__("base64").b64encode((ASSETS / "signboard_sample.jpg").read_bytes()).decode()
        r = c.post(f"/api/field/visits/{visit['id']}/complete",
                   json={"employee_id": visit["employee_id"], "lat": visit["lat"], "lng": visit["lng"], "signboard_photo": sign})
        r.raise_for_status()
        print(f"  field visit at {visit['scheduled_at'][11:16]} -> qr_status {r.json()['qr_status']}")
        c.post("/api/demo/reset").raise_for_status()  # leave a clean demo behind
    shutil.rmtree(settings.DATA_DIR / "uploads", ignore_errors=True)


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING, format="[%(name)s] %(levelname)s %(message)s")
    if args.check:
        sys.exit(1 if check_clips() else 0)
    print(f"DEMO_MODE={settings.DEMO_MODE} · Sarvam key {'set' if settings.SARVAM_API_KEY else 'NOT SET'}")
    print("Soundbox clips:")
    failed = record_clips()
    if args.journey:
        print("Finale journey (record mode):")
        run_journey()
    sys.exit(1 if failed else 0)
