"""Mock of PAN verification with the issuing authority."""
import re

from ..rules_engine import load_config, name_match_score
from . import simulate_latency

# The only PAN on record is the fictional one printed on our specimen card (scripts/make_specimens.py).
SPECIMEN_REGISTRY = {"ABCPS1234K": "RAMESH SHARMA"}


class PANVerificationClient:
    def verify(self, pan_number: str, name: str) -> dict:
        """-> {valid, name_on_record, status, name_match_score}. valid only when the PAN exists and the name matches."""
        simulate_latency()
        pan = re.sub(r"\s", "", pan_number or "").upper()
        on_record = SPECIMEN_REGISTRY.get(pan)
        if on_record is None:
            return {"valid": False, "name_on_record": None, "status": "NOT_FOUND", "name_match_score": None}
        score = name_match_score(name or "", on_record)
        ok = score >= load_config()["name_match_threshold"]
        return {"valid": ok, "name_on_record": on_record, "status": "VALID" if ok else "NAME_MISMATCH",
                "name_match_score": round(score, 1)}
