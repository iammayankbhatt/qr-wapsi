"""Mock of an outbound IVR (voice call) provider."""
from sqlmodel import Session

from ..db import engine
from ..events import publish
from ..models import ChatMessage
from . import simulate_latency


class IVRClient:
    def call(self, merchant_id: str, text_hi: str) -> dict:
        """Places a simulated call that reads text_hi aloud; logged in the chat history as an IVR entry."""
        simulate_latency()
        with Session(engine) as s:
            msg = ChatMessage(merchant_id=merchant_id, sender="agent", channel="IVR", text_hi=text_hi,
                              meta={"status": "COMPLETED", "duration_s": 42})
            s.add(msg)
            s.commit()
            s.refresh(msg)
        publish("ivr.call", merchant_id, {"call_id": msg.id, "text_hi": text_hi, "status": "COMPLETED"})
        return {"call_id": f"CALL-SIM{msg.id:06d}", "status": "COMPLETED", "duration_s": 42}
