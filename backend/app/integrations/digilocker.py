"""Mock of the DigiLocker issued-documents API."""
from typing import Optional

from ..models import Merchant
from . import simulate_latency


class DigiLockerClient:
    def fetch_document(self, merchant: Merchant, doc_type: str) -> Optional[dict]:
        """Issued document for the owner, or None. The prototype has no linked DigiLocker accounts, so this is
        always None and the shopkeeper uploads a photo instead."""
        simulate_latency()
        return None
