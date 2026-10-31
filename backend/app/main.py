import logging
import time
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware

from . import clock
from .config import settings
from .db import init_db
from .routers import audio, audit, demo, events, field, journeys, merchants, review
from .tool_client import get_tool_client, shutdown_tool_client

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    await run_in_threadpool(get_tool_client)  # starts the MCP tool server once (falls back to direct)
    yield
    await run_in_threadpool(shutdown_tool_client)


app = FastAPI(title="QR Wapsi", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health():
    return {"status": "ok", "demo_mode": settings.DEMO_MODE, "tool_transport": get_tool_client().active}


_probe_cache: dict[str, tuple[float, dict]] = {}
PROBE_TTL_S = 60


def _cached_probe(name: str, fn) -> dict:
    hit = _probe_cache.get(name)
    if hit and time.monotonic() - hit[0] < PROBE_TTL_S:
        return hit[1]
    try:
        out = fn()
    except Exception as e:  # noqa: BLE001
        out = {"status": "unreachable", "detail": f"{type(e).__name__}: {str(e)[:120]}"}
    _probe_cache[name] = (time.monotonic(), out)
    return out


def _probe_llm() -> dict:
    if settings.DEMO_MODE == "replay":
        n = len(list((settings.DEMO_CACHE_DIR / "llm").glob("*.json")))
        return {"status": "replay", "detail": f"served from demo cache ({n} entries); no network calls"}
    if not settings.GEMINI_API_KEY:
        return {"status": "no_key", "detail": "GEMINI_API_KEY is not set"}
    from .llm import _get_client
    _get_client().models.get(model=settings.GEMINI_MODEL)  # metadata only, no generation
    return {"status": "reachable", "detail": settings.GEMINI_MODEL}


def _probe_sarvam() -> dict:
    if settings.DEMO_MODE == "replay":
        return {"status": "replay", "detail": "no network calls in replay; Soundbox uses cached or browser voice"}
    if not settings.SARVAM_API_KEY:
        return {"status": "no_key", "detail": "SARVAM_API_KEY is not set"}
    r = httpx.get("https://api.sarvam.ai/", timeout=4)  # any HTTP answer means the service is reachable
    return {"status": "reachable", "detail": f"api.sarvam.ai answered HTTP {r.status_code}"}


@app.get("/api/system")
def system(probe: bool = False):
    """Which tool transport is active (mcp or direct), demo mode, models and the simulated clock.
    probe=true also checks Gemini and Sarvam reachability (never in replay mode)."""
    out = {"tool_transport": get_tool_client().info(), "demo_mode": settings.DEMO_MODE,
           "llm": {"model": settings.GEMINI_MODEL, "fallback_model": settings.GEMINI_FALLBACK_MODEL,
                   "key_set": bool(settings.GEMINI_API_KEY)},
           "sim_clock": clock.now().isoformat()}
    if probe:
        out["reachability"] = {"llm": _cached_probe("llm", _probe_llm), "sarvam": _cached_probe("sarvam", _probe_sarvam)}
    return out


for module, prefix in [
    (merchants, "/api/merchants"),
    (journeys, "/api"),
    (audit, "/api/audit"),
    (audio, "/api/audio"),
    (field, "/api/field"),
    (review, "/api/review"),
    (demo, "/api/demo"),
    (events, "/api"),
]:
    app.include_router(module.router, prefix=prefix)
