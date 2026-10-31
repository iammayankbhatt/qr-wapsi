import json
import logging

import httpx
import pytest
from google.genai import errors
from pydantic import ValidationError

from app import audit, llm
from app.llm import (DocumentExtraction, DraftedMessage, LLMUnavailable, PriorityExplanation, cache_key, draft_message,
                     explain_priority, extract_document, generate_json, propose_next_action)
from app.models import Merchant

GOOD_HI = "नमस्ते रमेश जी, Paytm की ओर से आपकी दुकान के पुन: सत्यापन के लिए कृपया पैन कार्ड की साफ़ फ़ोटो भेजें।"
GOOD_EN = "Hello Ramesh ji, this is Paytm about re-verification of your shop. Please send a clear photo of your PAN card."
ALLOWED = ["SEND_WHATSAPP", "WAIT", "ESCALATE"]


@pytest.fixture
def fake(monkeypatch, tmp_path):
    """Live mode, a key, a temp cache dir, no real sleeping, and a scripted _call_model."""
    monkeypatch.setattr(llm.settings, "DEMO_MODE", "live")
    monkeypatch.setattr(llm.settings, "GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(llm.settings, "GEMINI_MODEL", "primary")
    monkeypatch.setattr(llm.settings, "GEMINI_FALLBACK_MODEL", "fallback")
    monkeypatch.setattr(llm.settings, "DEMO_CACHE_DIR", tmp_path)

    class Fake:
        def __init__(self):
            self.script = []   # items: str (JSON text) or Exception, consumed in order
            self.calls = []    # (model, contents)
            self.sleeps = []

        def __call__(self, model, contents, schema):
            self.calls.append((model, contents))
            item = self.script.pop(0)
            if isinstance(item, Exception):
                raise item
            return item

    f = Fake()
    monkeypatch.setattr(llm, "_call_model", f)
    monkeypatch.setattr(llm, "_sleep", f.sleeps.append)
    return f


def explain_json(text="Big shop, long pause, nothing on file."):
    return json.dumps({"summary_en": text})


# ---------------------------------------------------------------- cache key

def test_cache_key_covers_task_model_prompt_and_image_bytes():
    base = cache_key("t", "m", "p", [b"img"])
    assert base == cache_key("t", "m", "p", [b"img"])
    assert len({base, cache_key("t2", "m", "p", [b"img"]), cache_key("t", "m2", "p", [b"img"]),
                cache_key("t", "m", "p2", [b"img"]), cache_key("t", "m", "p", [b"other"]), cache_key("t", "m", "p")}) == 6


# ---------------------------------------------------------------- live path: retry / fallback

def test_success_first_try(fake):
    fake.script = [explain_json()]
    out = generate_json("explain_priority", "prompt", PriorityExplanation)
    assert out.summary_en.startswith("Big shop") and [c[0] for c in fake.calls] == ["primary"]


def test_transient_errors_are_retried_with_backoff(fake):
    fake.script = [httpx.ReadTimeout("slow"), httpx.ReadTimeout("slow"), explain_json()]
    generate_json("explain_priority", "prompt", PriorityExplanation)
    assert [c[0] for c in fake.calls] == ["primary"] * 3      # first try + 2 retries
    assert fake.sleeps == [0.5, 1.0]


def test_falls_back_to_second_model_after_primary_retries_exhausted(fake):
    fake.script = [httpx.ReadTimeout("x")] * 3 + [explain_json()]
    out = generate_json("explain_priority", "prompt", PriorityExplanation)
    assert [c[0] for c in fake.calls] == ["primary"] * 3 + ["fallback"] and out.summary_en


def test_unknown_model_goes_straight_to_fallback_without_retrying(fake):
    fake.script = [errors.ClientError(404, {"error": {"message": "model not found"}}), explain_json()]
    generate_json("explain_priority", "prompt", PriorityExplanation)
    assert [c[0] for c in fake.calls] == ["primary", "fallback"] and fake.sleeps == []


def test_server_error_is_retried(fake):
    fake.script = [errors.ServerError(503, {"error": {"message": "overloaded"}}), explain_json()]
    generate_json("explain_priority", "prompt", PriorityExplanation)
    assert [c[0] for c in fake.calls] == ["primary", "primary"]


def test_everything_failing_raises_llm_unavailable(fake):
    fake.script = [httpx.ReadTimeout("x")] * (llm.PRIMARY_ATTEMPTS + llm.FALLBACK_ATTEMPTS)
    with pytest.raises(LLMUnavailable):
        generate_json("explain_priority", "prompt", PriorityExplanation)
    assert fake.script == []


def test_bad_credentials_fail_fast(fake):
    fake.script = [errors.ClientError(403, {"error": {"message": "API key not valid"}})]
    with pytest.raises(LLMUnavailable, match="credentials"):
        generate_json("explain_priority", "prompt", PriorityExplanation)
    assert len(fake.calls) == 1


def test_missing_api_key_raises_without_calling(fake, monkeypatch):
    monkeypatch.setattr(llm.settings, "GEMINI_API_KEY", "")
    with pytest.raises(LLMUnavailable, match="GEMINI_API_KEY"):
        generate_json("explain_priority", "prompt", PriorityExplanation)
    assert fake.calls == []


# ---------------------------------------------------------------- validation

def test_invalid_output_is_retried_once_with_the_error_appended(fake):
    fake.script = [explain_json("word " * 40), explain_json()]
    out = generate_json("explain_priority", "PROMPT", PriorityExplanation)
    assert out.summary_en.startswith("Big shop")
    assert [c[0] for c in fake.calls] == ["primary", "primary"]
    first, second = fake.calls[0][1][0], fake.calls[1][1][0]
    assert first == "PROMPT" and second.startswith("PROMPT") and "previous reply was invalid" in second and "25 words" in second


def test_still_invalid_after_retry_moves_to_fallback_then_raises(fake):
    bad = explain_json("word " * 40)
    fake.script = [bad, bad, bad, bad]
    with pytest.raises(LLMUnavailable):
        generate_json("explain_priority", "prompt", PriorityExplanation)
    assert [c[0] for c in fake.calls] == ["primary", "primary", "fallback", "fallback"]


def test_not_json_at_all_counts_as_invalid(fake):
    fake.script = ["Sorry, I cannot do that.", explain_json()]
    assert generate_json("explain_priority", "prompt", PriorityExplanation).summary_en


# ---------------------------------------------------------------- demo cache modes

def test_record_saves_and_replay_serves_from_cache_only(fake, monkeypatch, tmp_path):
    monkeypatch.setattr(llm.settings, "DEMO_MODE", "record")
    fake.script = [explain_json("recorded answer")]
    generate_json("explain_priority", "prompt", PriorityExplanation)
    saved = list((tmp_path / "llm").glob("*.json"))
    assert len(saved) == 1
    assert json.loads(saved[0].read_text(encoding="utf-8"))["response"] == {"summary_en": "recorded answer"}

    monkeypatch.setattr(llm.settings, "DEMO_MODE", "replay")
    monkeypatch.setattr(llm.settings, "GEMINI_API_KEY", "")
    fake.calls.clear()
    out = generate_json("explain_priority", "prompt", PriorityExplanation)
    assert out.summary_en == "recorded answer" and fake.calls == []


def test_live_mode_does_not_write_the_cache(fake, tmp_path):
    fake.script = [explain_json()]
    generate_json("explain_priority", "prompt", PriorityExplanation)
    assert not (tmp_path / "llm").exists()


def test_replay_miss_is_loud_and_never_calls_the_api(fake, monkeypatch, caplog):
    monkeypatch.setattr(llm.settings, "DEMO_MODE", "replay")
    with caplog.at_level(logging.WARNING, logger="qrwapsi.llm"):
        with pytest.raises(LLMUnavailable, match="cache miss"):
            generate_json("explain_priority", "never recorded", PriorityExplanation)
    assert fake.calls == []
    assert any("REPLAY CACHE MISS" in r.getMessage() and r.levelno == logging.WARNING for r in caplog.records)


def test_replay_rejects_a_cache_entry_that_no_longer_fits_the_schema(fake, monkeypatch, tmp_path):
    monkeypatch.setattr(llm.settings, "DEMO_MODE", "replay")
    key = cache_key("explain_priority", "primary", "prompt")
    (tmp_path / "llm").mkdir()
    (tmp_path / "llm" / f"{key}.json").write_text(json.dumps({"response": {"wrong": 1}}), encoding="utf-8")
    with pytest.raises(LLMUnavailable, match="schema"):
        generate_json("explain_priority", "prompt", PriorityExplanation)


def test_cache_key_ignores_which_model_actually_answered(fake, monkeypatch, tmp_path):
    monkeypatch.setattr(llm.settings, "DEMO_MODE", "record")
    fake.script = [httpx.ReadTimeout("x")] * 3 + [explain_json("from fallback")]
    generate_json("explain_priority", "prompt", PriorityExplanation)
    monkeypatch.setattr(llm.settings, "DEMO_MODE", "replay")
    assert generate_json("explain_priority", "prompt", PriorityExplanation).summary_en == "from fallback"


# ---------------------------------------------------------------- audit

def test_agent_facing_calls_write_an_llm_audit_entry(fake, session):
    fake.script = [explain_json()]
    generate_json("explain_priority", "prompt", PriorityExplanation, merchant_id="M0001")
    (entry,) = audit.entries_for("M0001", session)
    assert entry.actor == "llm" and entry.action == "LLM_EXPLAIN_PRIORITY"
    assert entry.payload["model"] == "primary" and entry.payload["cache_hit"] is False
    assert entry.payload["output"] == {"summary_en": "Big shop, long pause, nothing on file."}
    assert audit.verify_chain("M0001", session)["ok"]


def test_no_audit_entry_without_a_merchant(fake, session):
    fake.script = [explain_json()]
    generate_json("explain_priority", "prompt", PriorityExplanation)
    assert audit.entries_for("M0001", session) == []


def test_cache_hits_are_audited_too(fake, monkeypatch, session):
    monkeypatch.setattr(llm.settings, "DEMO_MODE", "record")
    fake.script = [explain_json()]
    generate_json("explain_priority", "prompt", PriorityExplanation)
    monkeypatch.setattr(llm.settings, "DEMO_MODE", "replay")
    generate_json("explain_priority", "prompt", PriorityExplanation, merchant_id="M0001")
    assert audit.entries_for("M0001", session)[-1].payload["cache_hit"] is True


# ---------------------------------------------------------------- schemas

@pytest.mark.parametrize("hi, en, why", [
    (GOOD_HI, GOOD_EN, None),
    ("Hello, this is Paytm. Please send a photo.", GOOD_EN, "Devanagari"),                      # not Hindi
    (GOOD_HI + " कृपया अपना OTP बताएं।", GOOD_EN, "OTPs"),                                      # asks for OTP
    ("नमस्ते, कृपया अपना ओटीपी बताएं। Paytm", GOOD_EN, "OTPs"),
    (GOOD_HI, GOOD_EN + " Also share your bank account number.", "bank"),
    ("नमस्ते रमेश जी, आपकी दुकान के सत्यापन के लिए पैन कार्ड की फ़ोटो भेजें।", GOOD_EN, "Paytm"),  # no Paytm
    (GOOD_HI + " शब्द" * 40, GOOD_EN, "40 words"),
])
def test_drafted_message_rules(hi, en, why):
    if why is None:
        assert DraftedMessage(text_hi=hi, text_en=en)
    else:
        with pytest.raises(ValidationError, match=why):
            DraftedMessage(text_hi=hi, text_en=en)


def test_explanation_word_limit():
    assert PriorityExplanation(summary_en="Short and sweet.")
    with pytest.raises(ValidationError):
        PriorityExplanation(summary_en="word " * 26)


def test_document_extraction_bounds():
    DocumentExtraction(doc_type="PAN", name=None, id_number=None, readable=False, issues=["blurry"], confidence=0.4)
    with pytest.raises(ValidationError):
        DocumentExtraction(doc_type="PASSPORT", readable=True, confidence=0.9)
    with pytest.raises(ValidationError):
        DocumentExtraction(doc_type="PAN", readable=True, confidence=1.5)


# ---------------------------------------------------------------- helpers

def hero():
    return Merchant(id="M0001", shop_name="Sharma Kirana Store", owner_name="Ramesh Sharma", category="kirana",
                    city="Noida", locality="Sector 62", lat=28.6, lng=77.3, turnover_band="10L_TO_40L")


def test_explain_priority_helper_sends_only_given_facts(fake):
    fake.script = [explain_json()]
    explain_priority(hero(), [{"label": "Active loan", "detail": "₹1.2L outstanding"}], write_audit=False)
    prompt = fake.calls[0][1][0]
    assert "Sharma Kirana Store" in prompt and "₹1.2L outstanding" in prompt and "25 words" in prompt


def test_draft_message_helper_prompt_carries_the_safety_rules(fake):
    fake.script = [json.dumps({"text_hi": GOOD_HI, "text_en": GOOD_EN})]
    out = draft_message(hero(), "DOCUMENT_REJECTED", "WHATSAPP", {"issue": "photo is blurry"}, write_audit=False)
    prompt = fake.calls[0][1][0]
    assert out.text_hi == GOOD_HI
    assert "Devanagari" in prompt and "NEVER ask for or mention OTPs" in prompt and "photo is blurry" in prompt and "Paytm" in prompt


def test_propose_next_action_only_accepts_allowed_actions(fake):
    fake.script = [json.dumps({"action": "SEND_WHATSAPP", "reason": "First contact.", "confidence": 0.9})]
    assert propose_next_action({"step": "COLLECT"}, ALLOWED, write_audit=False).action == "SEND_WHATSAPP"

    # an action outside the allowed list is invalid output: retried, then the fallback model, then LLMUnavailable
    fake.calls.clear()
    fake.script = [json.dumps({"action": "APPROVE_MERCHANT", "reason": "Looks fine.", "confidence": 0.9})] * 4
    with pytest.raises(LLMUnavailable):
        propose_next_action({"step": "COLLECT"}, ALLOWED, write_audit=False)


def test_propose_next_action_rejects_out_of_range_confidence(fake):
    fake.script = [json.dumps({"action": "WAIT", "reason": "r", "confidence": 3})] * 4
    with pytest.raises(LLMUnavailable):
        propose_next_action({"step": "X"}, ALLOWED, write_audit=False)


def test_propose_next_action_audits_under_the_state_merchant_id(fake, session):
    fake.script = [json.dumps({"action": "WAIT", "reason": "Waiting for reply.", "confidence": 0.7})]
    propose_next_action({"merchant_id": "M0001", "step": "COLLECT"}, ALLOWED)
    assert audit.entries_for("M0001", session)[0].action == "LLM_PROPOSE_NEXT_ACTION"


def test_extract_document_sends_the_image(fake, tmp_path):
    img = tmp_path / "pan.jpg"
    img.write_bytes(b"\xff\xd8\xff fake jpeg bytes")
    fake.script = [json.dumps({"doc_type": "PAN", "name": "RAMESH SHARMA", "id_number": "ABCZS1234K",
                               "readable": True, "issues": [], "confidence": 0.99})]
    out = extract_document(img)
    assert out.doc_type == "PAN" and out.id_number == "ABCZS1234K"
    contents = fake.calls[0][1]
    assert len(contents) == 2 and contents[1].inline_data.mime_type == "image/jpeg"
    assert contents[1].inline_data.data == img.read_bytes()


def test_extract_document_cache_key_depends_on_the_image(fake, monkeypatch):
    monkeypatch.setattr(llm.settings, "DEMO_MODE", "record")
    ok = json.dumps({"doc_type": "PAN", "name": "A", "id_number": None, "readable": True, "issues": [], "confidence": 0.9})
    fake.script = [ok, ok]
    extract_document(b"image-one")
    extract_document(b"image-two")
    assert len(list((llm.settings.DEMO_CACHE_DIR / "llm").glob("*.json"))) == 2
