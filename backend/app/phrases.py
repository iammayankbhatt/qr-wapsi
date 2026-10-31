"""Fixed, deterministic Hindi phrases. No LLM here: the Soundbox lines are short device announcements with
stable cache keys (scripts/warm_cache.py pre-records the exact clips), and the reactivation tool imports this
module without pulling the LLM into the code that switches a QR live."""

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


