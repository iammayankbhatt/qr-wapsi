import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware

from . import clock
from .config import settings
from .db import init_db
from .routers import audit, demo, events, field, journeys, merchants, review
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


@app.get("/api/system")
def system():
    """Which tool transport is active (mcp or direct), demo mode, models and the simulated clock."""
    return {"tool_transport": get_tool_client().info(), "demo_mode": settings.DEMO_MODE,
            "llm": {"model": settings.GEMINI_MODEL, "fallback_model": settings.GEMINI_FALLBACK_MODEL,
                    "key_set": bool(settings.GEMINI_API_KEY)},
            "sim_clock": clock.now().isoformat()}


for module, prefix in [
    (merchants, "/api/merchants"),
    (journeys, "/api"),
    (audit, "/api/audit"),
    (field, "/api/field"),
    (review, "/api/review"),
    (demo, "/api/demo"),
    (events, "/api"),
]:
    app.include_router(module.router, prefix=prefix)
