"""Read-only access to the (synthetic) Paytm merchant and payment data."""
from typing import Optional

from sqlmodel import Session, select

from ..db import engine
from ..models import Merchant


class PaytmDataClient:
    def get_merchant(self, merchant_id: str) -> Optional[Merchant]:
        with Session(engine) as s:
            return s.get(Merchant, merchant_id)

    def get_hourly_histogram(self, merchant_id: str) -> list[list[int]]:
        """7x24 payment counts, row 0 = Monday."""
        m = self.get_merchant(merchant_id)
        return m.hourly_txn_histogram if m else []

    def list_merchant_ids(self, qr_status: Optional[str] = None) -> list[str]:
        with Session(engine) as s:
            q = select(Merchant.id)
            if qr_status:
                q = q.where(Merchant.qr_status == qr_status)
            return list(s.exec(q.order_by(Merchant.id)))
