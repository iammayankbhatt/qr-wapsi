"""Merchant data, scoring and registry lookups."""
from typing import Optional

from sqlmodel import Session

from .. import audit
from ..db import engine
from ..integrations.ckycr import CKYCRClient
from ..integrations.digilocker import DigiLockerClient
from ..integrations.paytm_data import PaytmDataClient
from ..models import Document
from ..rules_engine import determine_route
from ..scoring import mule_risk, priority


def _merchant(merchant_id: str):
    m = PaytmDataClient().get_merchant(merchant_id)
    if m is None:
        raise KeyError(f"merchant {merchant_id} not found")
    return m


def get_merchant_profile(merchant_id: str) -> dict:
    """Synthetic merchant profile from Paytm data: shop, owner, location, QR status, documents on file."""
    m = _merchant(merchant_id)
    return {
        "merchant_id": m.id, "shop_name": m.shop_name, "owner_name": m.owner_name, "category": m.category,
        "locality": m.locality, "city": m.city, "lat": m.lat, "lng": m.lng, "turnover_band": m.turnover_band,
        "in_ckycr": m.in_ckycr, "qr_status": m.qr_status, "has_soundbox": m.has_soundbox,
        "monthly_gmv": m.monthly_gmv, "has_active_loan": m.has_active_loan, "open_hours": m.open_hours,
        "docs_status": m.docs_status,
    }


def score_merchant(merchant_id: str) -> dict:
    """Deterministic priority score with top reasons, mule-risk score with top features, and the KYC route."""
    m = _merchant(merchant_id)
    p = priority(m)
    return {"merchant_id": m.id, "priority_score": p.score, "reasons": p.reasons, "components": p.components,
            "mule_risk": mule_risk(m.risk_features), "route": determine_route(m)}


def check_ckycr(merchant_id: str) -> dict:
    """Search CKYCR. When a record is found it is stored as a CKYCR document for the rules engine."""
    m = _merchant(merchant_id)
    record = CKYCRClient().lookup(m)
    doc_id: Optional[int] = None
    if record:
        with Session(engine) as s:
            doc = Document(merchant_id=m.id, doc_type="CKYCR", file_path="ckycr://" + record["ckyc_id"],
                           extracted_fields=record, decision="ACCEPTED")
            s.add(doc)
            s.commit()
            s.refresh(doc)
            doc_id = doc.id
    audit.log(m.id, "agent", "CKYCR_CHECKED", {"found": bool(record), "document_id": doc_id,
                                                "ckyc_id": record["ckyc_id"] if record else None})
    return {"found": bool(record), "record": record, "document_id": doc_id}


def fetch_digilocker_document(merchant_id: str, doc_type: str) -> dict:
    """Try to pull an issued document from DigiLocker before asking the shopkeeper for a photo."""
    m = _merchant(merchant_id)
    doc = DigiLockerClient().fetch_document(m, doc_type)
    return {"found": doc is not None, "document": doc}
