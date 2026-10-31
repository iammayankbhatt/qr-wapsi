"""Shopkeeper messages: the LLM drafts them (llm.draft_message validates language and safety rules); these
fixed Hindi/English templates are the deterministic fallback when the LLM is unavailable or misses the cache.

Context passed to the LLM never contains dates or clock times that change between runs, so demo-cache
keys stay stable (visit times are given as a time of day only).
"""
from typing import Optional

from .. import llm
from ..documents import DOC_NAMES
from ..models import Merchant

TEMPLATES = {  # purpose -> (Hindi, English)
    "REQUEST_DOCUMENT": (
        "नमस्ते {first} जी, Paytm से संदेश: आपकी दुकान {shop} का QR दोबारा चालू करने के लिए री-वेरिफिकेशन ज़रूरी है। "
        "कृपया अपने {doc_hi} की साफ़ फ़ोटो यहाँ भेजें।",
        "Hello {first} ji, this is Paytm. To switch your shop {shop}'s QR back on we need to re-verify the shop. "
        "Please send a clear photo of your {doc_en} here."),
    "SOUNDBOX_ALERT": (
        "Paytm सूचना: आपका QR अभी बंद है। दोबारा चालू करने के लिए WhatsApp पर भेजा गया संदेश देखिए।",
        "Paytm alert: your QR is paused. Please check the WhatsApp message to switch it back on."),
    "REMINDER": (
        "नमस्ते {first} जी, Paytm से याद दिला रहे हैं: QR दोबारा चालू करने के लिए कृपया अपने {doc_hi} की फ़ोटो भेजें।",
        "Hello {first} ji, a reminder from Paytm: please send a photo of your {doc_en} to switch your QR back on."),
    "IVR_REQUEST": (
        "नमस्ते, यह Paytm से कॉल है। आपकी दुकान का QR दोबारा चालू करने के लिए कृपया WhatsApp पर अपने {doc_hi} की फ़ोटो भेजें।",
        "Hello, this is a call from Paytm. To switch your shop's QR back on, please send a photo of your {doc_en} on WhatsApp."),
    "DOCUMENT_REJECTED": (
        "{first} जी, Paytm से संदेश: {fix_hi}",
        "{first} ji, a message from Paytm: {fix_en}"),
    "DOCUMENT_ACCEPTED_NEXT": (
        "धन्यवाद {first} जी, आपका {done_hi} मिल गया और सही है। Paytm को अब आपके {doc_hi} की साफ़ फ़ोटो चाहिए।",
        "Thank you {first} ji, your {done_en} is received and correct. Paytm now needs a clear photo of your {doc_en}."),
    "OFFER_FORM60": (
        "कोई बात नहीं {first} जी। PAN न हो तो Paytm के लिए फ़ॉर्म 60 भरकर उसकी साफ़ फ़ोटो यहाँ भेज दीजिए।",
        "No problem {first} ji. If you do not have a PAN, please fill in Form 60 and send Paytm a clear photo of it here."),
    "REPLY_ACK": (
        "धन्यवाद {first} जी। Paytm को QR चालू करने के लिए आपके {doc_hi} की साफ़ फ़ोटो चाहिए।",
        "Thank you {first} ji. Paytm needs a clear photo of your {doc_en} to switch your QR back on."),
    "CONFIRM_VISIT": (
        "धन्यवाद {first} जी, आपके दस्तावेज़ सही हैं। Paytm के कर्मचारी {employee} {time_hi} बजे दुकान की जाँच के लिए आएंगे।",
        "Thank you {first} ji, your documents are in order. {employee} from Paytm will visit your shop at {time_en} for the shop check."),
    "FIELD_COLLECT": (
        "{first} जी, Paytm के कर्मचारी {employee} {time_hi} बजे आपकी दुकान पर आएंगे। कृपया अपना {doc_hi} तैयार रखें।",
        "{first} ji, {employee} from Paytm will visit your shop at {time_en}. Please keep your {doc_en} ready."),
    "QR_LIVE": (
        "बधाई हो {first} जी! Paytm सत्यापन पूरा हुआ। आपका QR फिर से चालू है।",
        "Congratulations {first} ji! Paytm verification is complete. Your QR is live again."),
}


# What each purpose means, given to the LLM with the purpose code (a bare code like QR_LIVE is ambiguous).
INTENTS = {
    "REQUEST_DOCUMENT": "Ask for a clear photo of the named document, sent as a reply in this WhatsApp chat.",
    "SOUNDBOX_ALERT": "Short spoken alert: the shop's QR is paused; please read the WhatsApp message Paytm just sent.",
    "REMINDER": "Polite reminder: we are still waiting for a photo of the named document in this WhatsApp chat.",
    "IVR_REQUEST": "Phone call: please send a photo of the named document on WhatsApp to switch the QR back on.",
    "DOCUMENT_REJECTED": "The photo could not be accepted. State the fix exactly as given and ask them to send a new photo here.",
    "DOCUMENT_ACCEPTED_NEXT": "Thank them: the first document is accepted. Now ask for a clear photo of the next named document here.",
    "OFFER_FORM60": "They have no PAN. Reassure them and ask for a photo of a filled-in Form 60 instead, sent here.",
    "REPLY_ACK": "Thank them for the reply and restate which document photo we still need, sent here.",
    "CONFIRM_VISIT": "Documents are verified. The named Paytm employee will visit the shop at the given time for a short shop check.",
    "FIELD_COLLECT": "The named Paytm employee will visit at the given time; please keep the named document ready.",
    "QR_LIVE": "Good news: verification is complete and the shop's QR is live again. Nothing more is needed.",
}


# Soundbox announcements: short, fixed Hindi lines (never LLM-drafted), so each has a stable cache key and
# scripts/warm_cache.py can pre-record the exact clip the device will play.
SOUNDBOX_LINES = {
    "OUTREACH": "Paytm सूचना: आपका QR अभी बंद है। दोबारा चालू करने के लिए WhatsApp पर भेजा गया संदेश देखिए।",
    "DOCUMENT_FIX": "Paytm सूचना: {fix_hi}",
    "VISIT_BOOKED": "Paytm सूचना: हमारे कर्मचारी आज {time_hi} बजे दुकान की जाँच के लिए आएंगे।",
    "QR_LIVE": "आपका QR फिर से चालू। धन्यवाद!",  # "Aapka QR phir se chalu. Dhanyavaad!"
}


def soundbox_line(purpose: str, **ctx) -> str:
    if "time" in ctx:
        ctx["time_hi"] = time_words(ctx.pop("time"))[0]
    return SOUNDBOX_LINES[purpose].format(**ctx)


def time_words(hhmm: str) -> tuple[str, str]:
    """'15:10' -> ('दोपहर 3:10', '3:10 PM')."""
    h, m = (int(x) for x in hhmm.split(":"))
    part = "सुबह" if h < 12 else "दोपहर" if h < 16 else "शाम"
    h12 = h % 12 or 12
    return f"{part} {h12}:{m:02d}", f"{h12}:{m:02d} {'AM' if h < 12 else 'PM'}"


def _fill(m: Merchant, ctx: dict) -> dict:
    doc = ctx.get("doc_type")
    done = ctx.get("done_doc_type")
    vals = {"first": m.owner_name.split()[0], "shop": m.shop_name, **ctx}
    if doc:
        vals["doc_en"], vals["doc_hi"] = DOC_NAMES[doc]
    if done:
        vals["done_en"], vals["done_hi"] = DOC_NAMES[done]
    if ctx.get("time"):
        vals["time_hi"], vals["time_en"] = time_words(ctx["time"])
    return vals


def template(m: Merchant, purpose: str, ctx: Optional[dict] = None) -> tuple[str, str]:
    hi, en = TEMPLATES[purpose]
    vals = _fill(m, ctx or {})
    return hi.format(**vals), en.format(**vals)


def compose(m: Merchant, purpose: str, channel: str, ctx: Optional[dict] = None) -> dict:
    """-> {text_hi, text_en, source: "llm" | "template"}."""
    ctx = ctx or {}
    try:
        llm_ctx = {"intent": INTENTS[purpose], **{k: v for k, v in _fill(m, ctx).items() if k not in ("first", "shop")}}
        d = llm.draft_message(m, purpose, channel, llm_ctx)
        return {"text_hi": d.text_hi, "text_en": d.text_en, "source": "llm"}
    except Exception:  # noqa: BLE001  (LLMUnavailable, cache miss, invalid draft: use the template)
        hi, en = template(m, purpose, ctx)
        return {"text_hi": hi, "text_en": en, "source": "template"}
