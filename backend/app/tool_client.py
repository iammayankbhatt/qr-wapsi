"""ToolClient: how the agent calls tools.

transport "mcp"    -> a stdio MCP ClientSession to app/mcp_server.py, started once (a subprocess plus a
                      background thread running its event loop). The agent's sync code calls through it.
transport "direct" -> plain in-process function calls (fallback, and what the tests use).

If MCP fails to start, or the MCP session dies, ToolClient logs a warning and switches to direct for good.
Expected refusals come back as {"ok": False, "error": ...}; ToolError means the tool itself crashed.
"""
import asyncio
import json
import logging
import os
import sys
import threading
from typing import Any, Optional

from .config import BACKEND_DIR, settings
from .tools import TOOLS

log = logging.getLogger("qrwapsi.tools")

START_TIMEOUT_S = 30
CALL_TIMEOUT_S = 120  # check_document may wait on several vision calls


# Tools with no external side effects (reads, deterministic checks, a result stored only once it succeeds):
# safe to re-run in-process if the MCP server process crashes mid-call. Messaging/booking/reactivation tools are not.
RETRY_DIRECT = {"check_document", "verify_pan", "check_ckycr", "fetch_digilocker_document", "get_merchant_profile",
                "score_merchant", "find_visit_slot", "run_compliance"}


class ToolError(Exception):
    pass


class ToolClient:
    def __init__(self, transport: str = "mcp"):
        self.requested = transport
        self.active = "direct"
        self.mcp_error: Optional[str] = None
        self.mcp_tools: list[str] = []
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._session = None
        self._stop: Optional[asyncio.Event] = None

    # ------------------------------------------------------------ lifecycle
    def start(self) -> "ToolClient":
        if self.requested != "mcp":
            self.active = "direct"
            return self
        try:
            self._start_mcp()
            self.active = "mcp"
            log.info("tool transport: mcp (%d tools)", len(self.mcp_tools))
        except Exception as e:  # noqa: BLE001
            self.mcp_error = f"{type(e).__name__}: {e}"
            self.active = "direct"
            log.warning("MCP tool server failed to start (%s); falling back to direct tool calls", self.mcp_error)
            self.stop()
        return self

    def _start_mcp(self) -> None:
        ready = threading.Event()
        failure: list[BaseException] = []
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever, name="mcp-client", daemon=True)
        self._thread.start()

        async def runner():
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client

            params = StdioServerParameters(command=sys.executable, args=["-m", "app.mcp_server"],
                                           cwd=str(BACKEND_DIR), env=dict(os.environ))
            settings.DATA_DIR.mkdir(parents=True, exist_ok=True)
            errlog = open(settings.DATA_DIR / "mcp_server.log", "a", encoding="utf-8")
            self._stop = asyncio.Event()
            try:
                async with stdio_client(params, errlog=errlog) as (read, write):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        self.mcp_tools = [t.name for t in (await session.list_tools()).tools]
                        missing = set(TOOLS) - set(self.mcp_tools)
                        if missing:
                            raise RuntimeError(f"MCP server is missing tools: {sorted(missing)}")
                        self._session = session
                        ready.set()
                        await self._stop.wait()
            except BaseException as e:  # noqa: BLE001
                failure.append(e)
                ready.set()
            finally:
                self._session = None
                errlog.close()

        self._runner = asyncio.run_coroutine_threadsafe(runner(), self._loop)
        if not ready.wait(START_TIMEOUT_S):
            raise TimeoutError("MCP server did not start in time")
        if failure:
            raise failure[0]

    def stop(self) -> None:
        if self._loop and self._stop is not None:
            self._loop.call_soon_threadsafe(self._stop.set)
            try:
                self._runner.result(timeout=10)
            except Exception:  # noqa: BLE001
                pass
        if self._loop:
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread:
            self._thread.join(timeout=5)
        self._loop = self._thread = self._session = self._stop = None

    # ------------------------------------------------------------ calls
    def call(self, name: str, /, **args: Any) -> dict:
        if name not in TOOLS:
            raise ToolError(f"unknown tool {name}")
        if self.active == "mcp":
            try:
                return self._call_mcp(name, args)
            except ToolError as e:
                if name not in RETRY_DIRECT:
                    raise
                # The MCP server process crashed inside a tool that is safe to re-run: retry in-process, which
                # also surfaces the real error (MCP only reports "Error executing tool").
                log.warning("MCP call %s crashed (%s); retrying in-process", name, e)
            except Exception as e:  # noqa: BLE001  (transport failure, not a tool failure)
                self.mcp_error = f"{type(e).__name__}: {e}"
                log.warning("MCP call %s failed (%s); switching to direct tool calls", name, self.mcp_error)
                self.active = "direct"
        try:
            return TOOLS[name](**args)
        except Exception as e:
            log.exception("tool %s failed", name)
            raise ToolError(f"{name} failed: {type(e).__name__}: {e}") from e

    def _call_mcp(self, name: str, args: dict) -> dict:
        if self._session is None:
            raise ConnectionError("MCP session is not running")
        fut = asyncio.run_coroutine_threadsafe(self._session.call_tool(name, args), self._loop)
        res = fut.result(timeout=CALL_TIMEOUT_S)
        text = "".join(getattr(c, "text", "") for c in res.content)
        if res.is_error:
            raise ToolError(f"{name} failed over MCP: {text}")
        if res.structured_content is not None:
            out = res.structured_content
            return out.get("result", out) if set(out) == {"result"} else out
        return json.loads(text) if text else {}

    def info(self) -> dict:
        return {"requested": self.requested, "active": self.active, "mcp_error": self.mcp_error,
                "tools": sorted(TOOLS), "mcp_tools": sorted(self.mcp_tools)}


_client: Optional[ToolClient] = None
_client_lock = threading.Lock()


def get_tool_client() -> ToolClient:
    global _client
    with _client_lock:
        if _client is None:
            _client = ToolClient(settings.TOOL_TRANSPORT).start()
        return _client


def shutdown_tool_client() -> None:
    global _client
    with _client_lock:
        if _client is not None:
            _client.stop()
            _client = None


def call_tool(name: str, /, **args: Any) -> dict:
    return get_tool_client().call(name, **args)
