"""Document checks: Gemini vision reads the fields, deterministic local code decides.

check_document() runs every check and stores one Document row. The first failing check, in this order,
is the rejection reason the shopkeeper hears, each with a specific fix in Hindi and English:
  BLURRY, TOO_DARK (local pixel checks) -> UNREADABLE, WRONG_DOCUMENT, PAN_FORMAT, LOW_CONFIDENCE
  (vision extraction) -> NAME_MISMATCH (rapidfuzz vs the owner's name) -> PAN_NOT_VERIFIED (issuing authority).

If the LLM is unavailable, the specimen images still work offline: their fields are known by file hash.
Any other image is then treated as unreadable (confidence 0), which leads to a retake and, after two
attempts, to human review. The LLM never accepts a document by itself.
"""
import hashlib
import io
import logging
import re
from pathlib import Path
from typing import Optional

import numpy as np
from PIL import Image
from sqlmodel import Session

from . import audit, llm
from .db import engine
from .events import publish
from .integrations.pan_verify import PANVerificationClient
from .models import Document, Merchant
from .rules_engine import load_config, name_match_score

log = logging.getLogger("qrwapsi.documents")

BLUR_THRESHOLD = 100.0  # Laplacian variance at 1000 px width; specimens: sharp ~1700-2000, blurry ~1
DARK_THRESHOLD = 50.0   # mean grey level 0-255
MIN_CONFIDENCE = 0.8
NORM_WIDTH = 1000
PAN_RE = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")

DOC_NAMES = {  # (English, Hindi)
    "PAN": ("PAN card", "PAN कार्ड"),
    "FORM60": ("Form 60", "फ़ॉर्म 60"),
    "OVD": ("ID proof (such as a voter ID or driving licence)", "पहचान पत्र (जैसे वोटर आईडी या ड्राइविंग लाइसेंस)"),
}

FIXES = {  # code -> (English fix, Hindi fix); {doc_en}/{doc_hi} are filled in
    "BLURRY": ("The photo is blurry. Please retake it in good light and hold the phone steady.",
               "फ़ोटो धुंधली है। कृपया अच्छी रोशनी में, फ़ोन स्थिर रखकर दोबारा फ़ोटो लें।"),
    "TOO_DARK": ("The photo is too dark. Please retake it in good light.",
                 "फ़ोटो बहुत अंधेरी है। कृपया अच्छी रोशनी में दोबारा फ़ोटो लें।"),
    "UNREADABLE": ("We could not read the document. Please send a clear photo of the whole {doc_en}.",
                   "दस्तावेज़ पढ़ा नहीं जा सका। कृपया पूरे {doc_hi} की साफ़ फ़ोटो भेजें।"),
    "WRONG_DOCUMENT": ("This does not look like your {doc_en}. Please send a photo of your {doc_en}.",
                       "यह आपका {doc_hi} नहीं लग रहा। कृपया अपने {doc_hi} की फ़ोटो भेजें।"),
    "PAN_FORMAT": ("The PAN number is not clear. Please send a clear photo of the PAN card.",
                   "PAN नंबर साफ़ नहीं दिख रहा। कृपया PAN कार्ड की साफ़ फ़ोटो भेजें।"),
    "LOW_CONFIDENCE": ("Some details are not clear. Please retake the photo of the whole {doc_en}.",
                       "कुछ जानकारी साफ़ नहीं दिख रही। कृपया पूरे {doc_hi} की दोबारा फ़ोटो लें।"),
    "NAME_MISMATCH": ("The name on the document does not match our records. Our team will contact you.",
                      "दस्तावेज़ पर लिखा नाम हमारे रिकॉर्ड से मेल नहीं खाता। हमारी टीम आपसे संपर्क करेगी।"),
    "PAN_NOT_VERIFIED": ("We could not verify this PAN with the Income Tax Department. Please check the card, "
                         "or send Form 60 if you do not have a PAN.",
                         "यह PAN आयकर विभाग से सत्यापित नहीं हो सका। कृपया कार्ड जाँचें, या PAN न हो तो फ़ॉर्म 60 भेजें।"),
}

# Offline fallback for the generated specimens only (scripts/make_specimens.py), matched by exact file hash.
_SPECIMENS = {
    "pan_sharp.jpg": dict(doc_type="PAN", name="RAMESH SHARMA", id_number="ABCZS1234K", readable=True, issues=[], confidence=0.97),
    "pan_blurry.jpg": dict(doc_type="PAN", name=None, id_number=None, readable=False, issues=["blurry"], confidence=0.3),
    "ovd_sharp.jpg": dict(doc_type="OVD", name="RAMESH SHARMA", id_number="DEMO-0000-1234-5678", readable=True, issues=[], confidence=0.97),
}
_ASSETS = Path(__file__).resolve().parent.parent / "demo_assets"


def _specimen_fields(data: bytes) -> Optional[dict]:
    digest = hashlib.sha256(data).hexdigest()
    for name, fields in _SPECIMENS.items():
        p = _ASSETS / name
        if p.exists() and hashlib.sha256(p.read_bytes()).hexdigest() == digest:
            return dict(fields)
    return None


def quality_metrics(data: bytes) -> dict:
    img = Image.open(io.BytesIO(data)).convert("L")
    w, h = img.size
    g = np.asarray(img.resize((NORM_WIDTH, max(round(h * NORM_WIDTH / w), 3))), dtype=float)
    lap = -4 * g[1:-1, 1:-1] + g[:-2, 1:-1] + g[2:, 1:-1] + g[1:-1, :-2] + g[1:-1, 2:]
    return {"laplacian_var": round(float(lap.var()), 1), "brightness": round(float(g.mean()), 1), "width": w, "height": h}


def extract(data: bytes, merchant_id: str) -> tuple[dict, str]:
    """-> (fields, source) with source "llm", "specimen_manifest" or "none"."""
    try:
        return llm.extract_document(data, merchant_id=merchant_id).model_dump(), "llm"
    except Exception as e:  # noqa: BLE001  (LLMUnavailable or anything unexpected: fall back, never crash)
        log.warning("document extraction via LLM unavailable (%s); using deterministic fallback", e)
    fields = _specimen_fields(data)
    if fields is not None:
        return fields, "specimen_manifest"
    return dict(doc_type="UNKNOWN", name=None, id_number=None, readable=False, issues=["could not be read"], confidence=0.0), "none"


def _fix(code: str, doc_type: str) -> tuple[str, str]:
    doc_en, doc_hi = DOC_NAMES.get(doc_type, DOC_NAMES["OVD"])
    en, hi = FIXES[code]
    return en.format(doc_en=doc_en), hi.format(doc_hi=doc_hi)


def _first_failure(doc_type: str, q: dict, f: dict, owner_name: str) -> tuple[Optional[str], dict]:
    """-> (failing code or None, extra fields: name_match_score, pan, authority verification)."""
    extra: dict = {}
    if q["laplacian_var"] < BLUR_THRESHOLD:
        return "BLURRY", extra
    if q["brightness"] < DARK_THRESHOLD:
        return "TOO_DARK", extra
    if not f.get("readable") or not f.get("name"):
        return "UNREADABLE", extra
    if f.get("doc_type") != doc_type:
        return "WRONG_DOCUMENT", extra
    if doc_type == "PAN":
        pan = re.sub(r"\s", "", f.get("id_number") or "").upper()
        extra["pan"] = pan
        if not PAN_RE.match(pan):
            return "PAN_FORMAT", extra
    if f.get("confidence", 0) < MIN_CONFIDENCE:
        return "LOW_CONFIDENCE", extra
    score = name_match_score(owner_name, f["name"])
    extra["name_match_score"] = round(score, 1)
    if score < load_config()["name_match_threshold"]:
        return "NAME_MISMATCH", extra
    if doc_type == "PAN":
        v = PANVerificationClient().verify(extra["pan"], f["name"])
        extra.update(authority_verified=v["valid"], authority_status=v["status"], name_on_record=v["name_on_record"])
        if not v["valid"]:
            return "PAN_NOT_VERIFIED", extra
    elif doc_type == "FORM60":
        # Simulated: an accepted Form 60 declaration is recorded with the authority in place of a PAN check.
        extra.update(authority_verified=True, authority_status="FORM60_RECORDED")
    return None, extra


def check_document(merchant_id: str, doc_type: str, file_path: str, attempt_no: int = 1) -> dict:
    """Check one uploaded photo of doc_type (PAN | FORM60 | OVD) and store the Document row."""
    data = Path(file_path).read_bytes()
    with Session(engine) as s:
        m = s.get(Merchant, merchant_id)
        if m is None:
            raise KeyError(merchant_id)
        owner_name = m.owner_name

    q = quality_metrics(data)
    fields, source = extract(data, merchant_id)
    code, extra = _first_failure(doc_type, q, fields, owner_name)
    decision = "REJECTED" if code else "ACCEPTED"
    fix_en, fix_hi = _fix(code, doc_type) if code else (None, None)

    extracted = {"name": fields.get("name"), "id_number": fields.get("id_number"), "doc_type_read": fields.get("doc_type"),
                 "readable": fields.get("readable"), "issues": fields.get("issues", []),
                 "confidence": fields.get("confidence", 0.0), "source": source, **extra}
    with Session(engine) as s:
        doc = Document(merchant_id=merchant_id, doc_type=doc_type, file_path=str(file_path), extracted_fields=extracted,
                       quality_metrics=q, decision=decision, reason=f"{code}: {fix_en}" if code else None,
                       attempt_no=attempt_no)
        s.add(doc)
        m = s.get(Merchant, merchant_id)
        status = dict(m.docs_status or {})
        if status.get(doc_type) != "VERIFIED":
            status[doc_type] = "VERIFIED" if decision == "ACCEPTED" else "REJECTED"
        m.docs_status = status
        s.add(m)
        s.commit()
        s.refresh(doc)
        doc_id = doc.id

    result = {"document_id": doc_id, "doc_type": doc_type, "decision": decision, "reason_code": code,
              "fix_en": fix_en, "fix_hi": fix_hi, "confidence": extracted["confidence"], "attempt_no": attempt_no,
              "extraction_source": source, "extracted": extracted, "quality": q}
    audit.log(merchant_id, "agent", "DOCUMENT_CHECKED", {k: v for k, v in result.items() if k != "fix_hi"})
    publish("document.checked", merchant_id, {"document_id": doc_id, "doc_type": doc_type, "decision": decision,
                                              "reason_code": code, "fix_en": fix_en, "fix_hi": fix_hi})
    return result
