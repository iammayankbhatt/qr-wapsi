"""Mock of the Central KYC Records Registry (CKYCR) search-and-download API."""
import hashlib
from typing import Optional

from ..models import Merchant
from . import simulate_latency


class CKYCRClient:
    def lookup(self, merchant: Merchant) -> Optional[dict]:
        """KYC record for the merchant's owner, or None when no record exists (driven by the seeded in_ckycr flag)."""
        simulate_latency()
        if not merchant.in_ckycr:
            return None
        digits = str(int(hashlib.sha256(merchant.id.encode()).hexdigest(), 16))[:14]
        return {
            "ckyc_id": f"SIM{digits}",  # synthetic identifier, never a real CKYC number
            "name": merchant.owner_name.upper(),
            "kyc_type": "INDIVIDUAL",
            "source": "CKYCR (simulated)",
        }
