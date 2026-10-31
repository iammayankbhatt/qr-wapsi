"""ToolClient over a real MCP stdio session, and the automatic fallback to direct calls."""
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.tool_client import ToolClient, ToolError
from app.tools import TOOLS

EXPECTED = {"get_merchant_profile", "score_merchant", "send_whatsapp", "play_soundbox_prompt", "place_ivr_call",
            "check_ckycr", "verify_pan", "check_document", "find_visit_slot", "book_visit", "run_compliance",
            "reactivate_qr", "open_review_case"}


def test_every_requested_tool_exists():
    assert EXPECTED <= set(TOOLS)


@pytest.fixture(scope="module")
def mcp_client():
    c = ToolClient("mcp").start()
    yield c
    c.stop()


def test_mcp_transport_lists_and_calls_tools(mcp_client):
    assert mcp_client.active == "mcp", mcp_client.mcp_error
    assert set(mcp_client.mcp_tools) == set(TOOLS)
    assert mcp_client.call("get_merchant_profile", merchant_id="M0001")["shop_name"] == "Sharma Kirana Store"
    assert mcp_client.call("verify_pan", pan_number="ABCPS1234K", name="Ramesh Sharma")["valid"] is True
    assert mcp_client.call("find_visit_slot", merchant_id="M0001")["slot"].endswith("T15:10:00")


def test_mcp_tool_failure_is_a_tool_error_not_a_transport_switch(mcp_client):
    with pytest.raises(ToolError):
        mcp_client.call("get_merchant_profile", merchant_id="NOPE")
    assert mcp_client.active == "mcp"


def test_mcp_startup_failure_falls_back_to_direct(monkeypatch):
    def broken(self):
        raise FileNotFoundError("mcp server binary missing")

    monkeypatch.setattr(ToolClient, "_start_mcp", broken)
    c = ToolClient("mcp").start()
    assert c.active == "direct" and "missing" in c.mcp_error
    assert c.call("score_merchant", merchant_id="M0001")["route"] == "SMALL_MERCHANT"


def test_system_endpoint_reports_the_active_transport():
    with TestClient(app) as client:
        info = client.get("/api/system").json()
    assert info["tool_transport"]["active"] == "direct"  # tests run with TOOL_TRANSPORT=direct
    assert info["demo_mode"] == "replay"
