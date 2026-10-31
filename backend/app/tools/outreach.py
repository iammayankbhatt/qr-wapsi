"""Shopkeeper contact channels: WhatsApp, Soundbox, IVR."""
from typing import Optional

from .. import audit
from ..integrations.ivr import IVRClient
from ..integrations.paytm_data import PaytmDataClient
from ..integrations.soundbox import SoundboxClient
from ..integrations.whatsapp import WhatsAppClient


def send_whatsapp(merchant_id: str, text_hi: str, text_en: str) -> dict:
    """Send a WhatsApp message (Hindi, with an English rendering for the operator) to the shopkeeper."""
    res = WhatsAppClient().send(merchant_id, text_hi, text_en)
    audit.log(merchant_id, "agent", "WHATSAPP_SENT", {"message_id": res["message_id"], "text_hi": text_hi, "text_en": text_en})
    return {"ok": True, **res}


def play_soundbox_prompt(merchant_id: str, text_hi: str, audio_ref: Optional[str] = None) -> dict:
    """Speak a Hindi prompt on the shop's Soundbox."""
    m = PaytmDataClient().get_merchant(merchant_id)
    if m is None or not m.has_soundbox:
        return {"ok": False, "error": "merchant has no Soundbox"}
    res = SoundboxClient().speak(merchant_id, text_hi, audio_ref)
    audit.log(merchant_id, "agent", "SOUNDBOX_PROMPT_PLAYED", {"text_hi": text_hi, "audio_ref": audio_ref})
    return {"ok": True, **res}


def place_ivr_call(merchant_id: str, text_hi: str) -> dict:
    """Place an automated voice call that reads a Hindi message to the shopkeeper."""
    res = IVRClient().call(merchant_id, text_hi)
    audit.log(merchant_id, "agent", "IVR_CALL_PLACED", {"call_id": res["call_id"], "status": res["status"], "text_hi": text_hi})
    return {"ok": True, **res}
