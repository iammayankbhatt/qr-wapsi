"""Mock of the WhatsApp Business messaging API. Messages land in the ChatMessage table the ShopSimulator reads."""
from typing import Optional

from sqlmodel import Session

from ..db import engine
from ..events import publish
from ..models import ChatMessage
from . import simulate_latency


class WhatsAppClient:
    def send(self, merchant_id: str, text_hi: str, text_en: str) -> dict:
        simulate_latency()
        with Session(engine) as s:
            msg = ChatMessage(merchant_id=merchant_id, sender="agent", channel="WHATSAPP", text_hi=text_hi, text_en=text_en)
            s.add(msg)
            s.commit()
            s.refresh(msg)
        publish("chat.message", merchant_id, {"message_id": msg.id, "sender": "agent", "channel": "WHATSAPP",
                                              "text_hi": text_hi, "text_en": text_en})
        return {"message_id": f"wamid.SIM{msg.id:06d}", "status": "sent"}

    def receive(self, merchant_id: str, text: str = "", attachment: Optional[str] = None) -> dict:
        """Inbound webhook: what the shopkeeper sent (text and/or a photo)."""
        with Session(engine) as s:
            msg = ChatMessage(merchant_id=merchant_id, sender="shopkeeper", channel="WHATSAPP", text_hi=text,
                              attachment=attachment)
            s.add(msg)
            s.commit()
            s.refresh(msg)
        publish("chat.message", merchant_id, {"message_id": msg.id, "sender": "shopkeeper", "channel": "WHATSAPP",
                                              "text_hi": text, "attachment": attachment})
        return {"message_id": f"wamid.SIM{msg.id:06d}"}
