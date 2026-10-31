"""Mock of the Paytm Soundbox device API. Pushes SSE events that the SoundboxWidget plays and displays."""
from typing import Optional

from ..events import publish
from . import simulate_latency


class SoundboxClient:
    def speak(self, merchant_id: str, text_hi: str, audio_ref: Optional[str] = None) -> dict:
        """audio_ref names a cached TTS clip; when None the widget falls back to the browser's hi-IN voice."""
        simulate_latency()
        publish("soundbox.speak", merchant_id, {"text_hi": text_hi, "audio_ref": audio_ref})
        return {"status": "PLAYED", "audio_ref": audio_ref}

    def set_status(self, merchant_id: str, status: str) -> dict:
        simulate_latency()
        publish("soundbox.status", merchant_id, {"status": status})
        return {"status": status}
