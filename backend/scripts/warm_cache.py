"""Fill backend/demo_cache/ so the finale runs offline with DEMO_MODE=replay.

Run (from backend/), with GEMINI_API_KEY and SARVAM_API_KEY in .env:
  python scripts/warm_cache.py               DEMO_MODE=record: reset the demo, run the finale for M0001 and the
                                             escalation demo (approve + reject) through the API, then replay the same
                                             path with the network blocked and report any cache miss
  python scripts/warm_cache.py --prune       the same, then delete cache entries this run did not use
  python scripts/warm_cache.py --clips-only  only the four fixed Soundbox clips for M0001
  python scripts/warm_cache.py --check       no network: list what is cached
Resets the demo database before and after.
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
parser.add_argument("--clips-only", action="store_true", help="only record the four fixed Soundbox clips")
parser.add_argument("--prune", action="store_true", help="delete cache entries the demo path did not use")
parser.add_argument("--check", action="store_true", help="only list what is cached; never calls an API")
parser.add_argument("--journey", action="store_true", help=argparse.SUPPRESS)  # old flag: the full run is now the default
args = parser.parse_args()
if not args.check:
    os.environ["DEMO_MODE"] = "record"  # must be set before app.config is imported
    os.environ.setdefault("TOOL_TRANSPORT", "direct")

import logging  # noqa: E402

from sqlmodel import Session  # noqa: E402

from app import clock, voice  # noqa: E402
from app.phrases import soundbox_line  # noqa: E402
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


class MissCounter(logging.Handler):
    """Counts the loud replay-miss warnings llm.py and voice.py log."""
    def __init__(self):
        super().__init__(logging.WARNING)
        self.misses: list[str] = []

    def emit(self, record):
        if "CACHE MISS" in record.getMessage():
            self.misses.append(record.getMessage().split(" — ")[0])


def list_cache(since: float | None = None) -> list[Path]:
    """Print every cached key. Entries written before `since` were not used by this run (stale)."""
    import json
    stale = []
    rows = []
    for p in sorted((settings.DEMO_CACHE_DIR / "llm").glob("*.json")):
        d = json.loads(p.read_text(encoding="utf-8"))
        rows.append((p, "llm  ", d["task_name"], d["key"][:16]))
    for p in sorted((settings.DEMO_CACHE_DIR / "audio").glob("*.wav")):
        rows.append((p, "audio", "soundbox clip", p.stem[:16]))
    texts = {voice.audio_key(t): t for _, t in fixed_lines()}
    for p, kind, task, key in sorted(rows, key=lambda r: (r[1], r[2])):
        used = since is None or p.stat().st_mtime >= since
        stale += [] if used else [p]
        extra = texts.get(p.stem, "") if kind == "audio" else ""
        print(f"  {kind} {key}…  {task:22s} {'' if used else 'STALE '}{extra}")
    print(f"  total: {len(rows)} entries ({len(rows) - len(stale)} used by this run, {len(stale)} stale)")
    return stale


def run_journey() -> None:
    """The finale through the HTTP API: in record mode every LLM call and Soundbox clip lands in demo_cache/."""
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
        # escalation demo: /demo "Trigger a risky merchant" twice, approve the first and reject the second
        for decision, note in (("APPROVE", None), ("REJECT", "Pass-through pattern: round amounts at night. Refer to the risk team.")):
            risky = c.post("/api/demo/risky").json()
            case = next(x for x in c.get("/api/review").json()["cases"] if x["merchant_id"] == risky["merchant_id"])
            v = c.post(f"/api/review/{case['id']}/decide", json={"decided_by": "A. Mehta (Ops)", "decision": decision, "note": note})
            v.raise_for_status()
            print(f"  escalation {risky['merchant_id']} {decision} -> step {v.json()['step']}")
        c.post("/api/demo/reset").raise_for_status()  # leave a clean demo behind
    shutil.rmtree(settings.DATA_DIR / "uploads", ignore_errors=True)


if __name__ == "__main__":
    import time

    logging.basicConfig(level=logging.ERROR, format="[%(name)s] %(levelname)s %(message)s")
    if args.check:
        missing = check_clips()
        print("Cached keys:")
        list_cache()
        sys.exit(1 if missing else 0)
    print(f"DEMO_MODE={settings.DEMO_MODE} · Gemini key {'set' if settings.GEMINI_API_KEY else 'NOT SET'} · "
          f"Sarvam key {'set' if settings.SARVAM_API_KEY else 'NOT SET'}")
    started = time.time() - 1
    print("1. Soundbox clips (record):")
    failed = record_clips()
    if not args.clips_only:
        print("2. Finale + escalation demo (record):")
        run_journey()
        print("3. Same path again in replay mode, network blocked:")
        from app import netguard
        settings.DEMO_MODE = "replay"
        netguard.install()
        counter = MissCounter()
        logging.getLogger("qrwapsi").addHandler(counter)
        run_journey()
        print(f"  replay cache misses: {len(counter.misses)}")
        for m in counter.misses:
            print("   ", m)
        print(f"  blocked network calls: {netguard.status()['blocked_calls']}")
        failed += len(counter.misses) + netguard.status()["blocked_calls"]
    print("Cached keys:")
    stale = list_cache(None if args.clips_only else started)
    if args.prune and not args.clips_only and stale:
        for p in stale:
            p.unlink()
        print(f"  pruned {len(stale)} stale entries")
    print("RESULT:", "OK — the demo is fully cached" if not failed else f"PROBLEMS: {failed}")
    sys.exit(1 if failed else 0)
