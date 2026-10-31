"""Document checks and PAN verification."""
from .. import documents
from ..integrations.pan_verify import PANVerificationClient


def verify_pan(pan_number: str, name: str) -> dict:
    """Verify a PAN and the holder's name with the issuing authority."""
    return PANVerificationClient().verify(pan_number, name)


def check_document(merchant_id: str, doc_type: str, file_path: str, attempt_no: int = 1) -> dict:
    """Check an uploaded document photo (PAN | FORM60 | OVD): quality, extraction, format, name match, authority.
    Stores the result; returns the decision and, when rejected, a specific fix for the shopkeeper."""
    return documents.check_document(merchant_id, doc_type, file_path, attempt_no)
