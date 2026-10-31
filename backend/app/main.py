import logging
import time
import uuid
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from . import clock, netguard
from .config import settings
from .db import init_db
from .routers import audio, audit, demo, events, field, journeys, merchants, review
from .tool_client import get_tool_client, shutdown_tool_client

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("qrwapsi.api")
SLOW_REQUEST_MS = 1000

if settings.DEMO_MODE == "replay":
    netguard.install()  # replay must work with Wi-Fi off: any network call fails fast and is logged


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    await run_in_threadpool(get_tool_client)  # starts the MCP tool server once (falls back to direct)
    await run_in_threadpool(_warm_up)
    yield
    await run_in_threadpool(shutdown_tool_client)


def _warm_up() -> None:
    """Pay one-time costs at startup, not on the presenter's first click: compile the journey graph and
    build today's seed rows (used by every demo reset)."""
    from datetime import date

    from scripts.seed import _seed_rows

    from .agent import service
    started = time.perf_counter()
    service.get_graph()
    _seed_rows(date.today())
    log.info("warm-up done in %.1f s", time.perf_counter() - started)


app = FastAPI(title="QR Wapsi", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def timing(request: Request, call_next):
    started = time.perf_counter()
    response = await call_next(request)
    ms = (time.perf_counter() - started) * 1000
    response.headers["X-Response-Time-ms"] = f"{ms:.0f}"
    if ms > SLOW_REQUEST_MS and request.url.path != "/api/events":
        log.warning("slow request %s %s took %.0f ms", request.method, request.url.path, ms)
    return response


@app.exception_handler(Exception)
async def unhandled_error(request: Request, exc: Exception):
    """Full traceback to the server log; a short, friendly message (with an id to find it) to the screen."""
    err_id = uuid.uuid4().hex[:8]
    log.error("unhandled error %s on %s %s", err_id, request.method, request.url.path, exc_info=exc)
    return JSONResponse(status_code=500, content={
        "detail": f"Something went wrong on the server (error {err_id}). The full error is in the server log."})


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
           "sim_clock": clock.now().isoformat(), "offline_guard": netguard.status()}
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
