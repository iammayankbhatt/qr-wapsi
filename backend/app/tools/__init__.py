"""Agent tools, defined once. mcp_server.py exposes them over MCP; ToolClient's direct transport calls them
in-process. Every tool takes JSON-friendly arguments and returns a JSON-friendly dict."""
from .compliance import open_review_case, reactivate_qr, run_compliance
from .docs import check_document, verify_pan
from .merchant import check_ckycr, fetch_digilocker_document, get_merchant_profile, score_merchant
from .outreach import place_ivr_call, play_soundbox_prompt, send_whatsapp
from .visits import book_visit, find_visit_slot

TOOLS = {f.__name__: f for f in (
    get_merchant_profile, score_merchant, check_ckycr, fetch_digilocker_document,
    send_whatsapp, play_soundbox_prompt, place_ivr_call,
    verify_pan, check_document,
    find_visit_slot, book_visit,
    run_compliance, reactivate_qr, open_review_case,
)}
