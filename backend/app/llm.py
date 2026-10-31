"""The only module that calls Gemini.

generate_json(task_name, prompt, schema, images=None) -> schema instance
  * 15 s timeout, 2 retries with backoff on transient errors, then the fallback model, then LLMUnavailable
  * output is validated with the Pydantic schema; one retry with the error appended on validation failure
  * DEMO_MODE: live = call the API | record = call the API and save to demo_cache/llm/ | replay = cache only

The LLM proposes, drafts, explains and extracts. It never decides compliance (see rules_engine.py), and every
caller must have a deterministic fallback for LLMUnavailable.
"""
import argparse
import hashlib
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any, Iterable, Literal, Optional, Union

from pydantic import BaseModel, Field, ValidationError, create_model, field_validator

from . import audit
from .config import settings

log = logging.getLogger("qrwapsi.llm")

TIMEOUT_S = 15
PRIMARY_ATTEMPTS = 3        # first try + 2 retries
FALLBACK_ATTEMPTS = 2
BACKOFF_S = 0.5             # 0.5 s, then 1 s
TEMPERATURE = 0.2
THINKING_BUDGET = 0         # these tasks are short drafts and field extraction; thinking only adds seconds

_sleep = time.sleep         # patched in tests
_client = None


class LLMUnavailable(Exception):
    """No usable LLM answer (no key, replay cache miss, repeated failures, invalid output)."""


# ---------------------------------------------------------------- cache

def _image_hash(img: bytes) -> str:
    return hashlib.sha256(img).hexdigest()


def cache_key(task_name: str, model: str, prompt: str, images: Iterable[bytes] = ()) -> str:
    """sha256(task_name + model + prompt + image hashes). `model` is always the configured primary model,
    so a cache recorded while the fallback model answered is still found in replay."""
    raw = task_name + model + prompt + "".join(_image_hash(i) for i in images)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _cache_path(key: str) -> Path:
    return settings.DEMO_CACHE_DIR / "llm" / f"{key}.json"


def _cache_read(key: str) -> Optional[dict]:
    p = _cache_path(key)
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))["response"]


def _cache_write(key: str, task_name: str, model: str, response: dict) -> None:
    p = _cache_path(key)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"task_name": task_name, "model": model, "key": key, "response": response},
                            ensure_ascii=False, indent=2), encoding="utf-8")


# ---------------------------------------------------------------- API call

def _get_client():
    global _client
    if _client is None:
        from google import genai
        from google.genai import types
        _client = genai.Client(api_key=settings.GEMINI_API_KEY,
                               http_options=types.HttpOptions(timeout=TIMEOUT_S * 1000))
    return _client


def _call_model(model: str, contents: list, schema: type[BaseModel]) -> str:
    """One raw call; returns the JSON text. Tests replace this."""
    from google.genai import errors, types

    def go(thinking: bool) -> str:
        cfg = types.GenerateContentConfig(
            response_mime_type="application/json", response_schema=schema, temperature=TEMPERATURE,
            thinking_config=types.ThinkingConfig(thinking_budget=THINKING_BUDGET) if thinking else None)
        resp = _get_client().models.generate_content(model=model, contents=contents, config=cfg)
        if not resp.text:
            raise ValueError("empty response from model")
        return resp.text

    try:
        return go(thinking=True)
    except errors.ClientError as e:
        # Some models (the flash-lite fallback) reject thinking_budget with an unhelpful generic 400:
        # ask again without it. A genuinely bad request fails again and is handled by the caller.
        if e.code == 400:
            log.info("model %s rejected the thinking setting; retrying without it", model)
            return go(thinking=False)
        raise


def _classify(exc: Exception) -> str:
    """'retry' (transient) | 'next_model' (this model cannot answer) | 'fatal' (key/permission problem)."""
    import httpx
    from google.genai import errors
    if isinstance(exc, (httpx.TransportError, TimeoutError)):
        return "retry"
    if isinstance(exc, errors.APIError):
        code = exc.code or 0
        if code in (401, 403):
            return "fatal"
        if code in (408, 429) or code >= 500:
            return "retry"
        return "next_model"  # 400 bad request, 404 unknown model, ...
    return "next_model"


def _contents(prompt: str, images: list[bytes]) -> list:
    if not images:
        return [prompt]
    from google.genai import types
    return [prompt] + [types.Part.from_bytes(data=i, mime_type=_mime(i)) for i in images]


def _mime(data: bytes) -> str:
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return "image/jpeg"


def _validated(model: str, prompt: str, images: list[bytes], schema: type[BaseModel]) -> BaseModel:
    """Call one model once; on a schema failure retry once with the validation error appended."""
    contents = _contents(prompt, images)
    text = _call_model(model, contents, schema)
    try:
        return schema.model_validate_json(text)
    except ValidationError as err:
        log.warning("LLM output failed validation (%s); retrying once with the error appended", _short(err))
        retry = prompt + (f"\n\nYour previous reply was invalid: {_short(err)}\n"
                          "Reply again with only valid JSON that satisfies the schema and every rule above.")
        return schema.model_validate_json(_call_model(model, _contents(retry, images), schema))


def _short(err: Exception) -> str:
    return " | ".join(str(err).split("\n")[:4])[:400]


def _live_call(prompt: str, images: list[bytes], schema: type[BaseModel]) -> tuple[BaseModel, str]:
    if not settings.GEMINI_API_KEY:
        raise LLMUnavailable("GEMINI_API_KEY is not set")
    last: Optional[Exception] = None
    for model, attempts in ((settings.GEMINI_MODEL, PRIMARY_ATTEMPTS), (settings.GEMINI_FALLBACK_MODEL, FALLBACK_ATTEMPTS)):
        for attempt in range(attempts):
            try:
                return _validated(model, prompt, images, schema), model
            except ValidationError as e:
                last = e
                log.warning("model %s returned invalid output twice; moving on", model)
                break
            except Exception as e:  # noqa: BLE001  (SDK raises many types; classified below)
                last = e
                kind = _classify(e)
                log.warning("LLM call failed model=%s attempt=%d/%d kind=%s: %s", model, attempt + 1, attempts, kind, _short(e))
                if kind == "fatal":
                    raise LLMUnavailable(f"Gemini rejected the credentials: {_short(e)}") from e
                if kind == "next_model":
                    break
                if attempt < attempts - 1:
                    _sleep(BACKOFF_S * 2**attempt)
    raise LLMUnavailable(f"all Gemini models failed; last error: {_short(last) if last else 'n/a'}") from last


# ---------------------------------------------------------------- public entry point

def generate_json(task_name: str, prompt: str, schema: type[BaseModel], images: Optional[list[bytes]] = None,
                  *, merchant_id: Optional[str] = None) -> Any:
    """Return a validated `schema` instance. Pass merchant_id for agent-facing calls to write an audit entry (actor "llm")."""
    images = images or []
    mode = settings.DEMO_MODE
    key = cache_key(task_name, settings.GEMINI_MODEL, prompt, images)
    started = time.perf_counter()
    cache_hit, model_used = False, settings.GEMINI_MODEL

    if mode == "replay":
        try:
            cached = _cache_read(key)
        except (OSError, ValueError, KeyError) as e:
            raise LLMUnavailable(f"unreadable demo cache entry {key[:12]}: {e}") from e
        if cached is None:
            log.warning("!!! REPLAY CACHE MISS task=%s key=%s — no live call allowed in replay mode; caller must use its "
                        "deterministic fallback. Run scripts/warm_cache.py (DEMO_MODE=record) to fill demo_cache/.", task_name, key[:12])
            raise LLMUnavailable(f"replay cache miss for task {task_name} ({key[:12]})")
        try:
            result = schema.model_validate(cached)
        except ValidationError as e:
            raise LLMUnavailable(f"cached response for {task_name} no longer matches its schema: {_short(e)}") from e
        cache_hit, model_used = True, "cache"
    else:
        result, model_used = _live_call(prompt, images, schema)
        if mode == "record":
            _cache_write(key, task_name, settings.GEMINI_MODEL, result.model_dump(mode="json"))

    latency_ms = round((time.perf_counter() - started) * 1000)
    log.info("LLM task=%s model=%s latency=%dms cache_hit=%s mode=%s", task_name, model_used, latency_ms, cache_hit, mode)

    if merchant_id:
        try:
            audit.log(merchant_id, "llm", f"LLM_{task_name.upper()}", {
                "task": task_name, "model": model_used, "latency_ms": latency_ms, "cache_hit": cache_hit,
                "mode": mode, "cache_key": key, "images": len(images), "output": result.model_dump(mode="json"),
            })
        except Exception:  # noqa: BLE001  (an audit hiccup must not break the demo path)
            log.exception("failed to write LLM audit entry")
    return result


# ================================================================ schemas and helpers

_BANNED = ("otp", "ओटीपी", "pin", "पिन", "cvv", "password", "पासवर्ड", "account number", "खाता संख्या", "खाता नंबर",
           "बैंक खाता", "bank account", "card number", "कार्ड नंबर")
_DEVANAGARI = range(0x0900, 0x0980)


def _has_devanagari(s: str) -> bool:
    return any(ord(c) in _DEVANAGARI for c in s)


class PriorityExplanation(BaseModel):
    summary_en: str

    @field_validator("summary_en")
    @classmethod
    def _short_enough(cls, v: str) -> str:
        if not v.strip() or len(v.split()) > 25:
            raise ValueError("summary_en must be 1 to 25 words")
        return v.strip()


class DraftedMessage(BaseModel):
    text_hi: str
    text_en: str

    @field_validator("text_hi", "text_en")
    @classmethod
    def _safe(cls, v: str) -> str:
        low = v.lower()
        if len(v.split()) > 40:
            raise ValueError("each message must be at most 40 words")
        if any(b in low for b in _BANNED):
            raise ValueError("message must never mention OTPs, PINs, passwords or bank/card details")
        if "paytm" not in low and "पेटीएम" not in v:
            raise ValueError("message must say it is from Paytm")
        return v.strip()

    @field_validator("text_hi")
    @classmethod
    def _devanagari(cls, v: str) -> str:
        if not _has_devanagari(v):
            raise ValueError("text_hi must be written in Devanagari Hindi")
        return v


class NextAction(BaseModel):
    action: str
    reason: str
    confidence: float = Field(ge=0, le=1)

    @field_validator("reason")
    @classmethod
    def _one_line(cls, v: str) -> str:
        v = " ".join(v.split())
        if not v or len(v) > 240:
            raise ValueError("reason must be one short line")
        return v


class DocumentExtraction(BaseModel):
    doc_type: Literal["PAN", "FORM60", "OVD", "UNKNOWN"]
    name: Optional[str] = None
    id_number: Optional[str] = None
    readable: bool
    issues: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)


def _merchant_facts(m: Any) -> dict:
    """Minimum facts the model needs; nothing sensitive beyond the synthetic shop and owner names."""
    return {"shop_name": m.shop_name, "owner_name": m.owner_name, "category": m.category,
            "locality": m.locality, "city": m.city, "has_soundbox": m.has_soundbox}


def explain_priority(merchant: Any, reasons: list[dict], *, write_audit: bool = True) -> PriorityExplanation:
    prompt = (
        "You explain to a Paytm operations manager why a merchant whose QR is paused is ranked where it is in the "
        "RBI re-KYC queue.\n"
        "Use ONLY the facts below; do not invent numbers. You do not decide compliance.\n"
        "Write one plain-English sentence of at most 25 words.\n\n"
        f"Merchant: {json.dumps(_merchant_facts(merchant), ensure_ascii=False)}\n"
        f"Top ranking reasons: {json.dumps(reasons, ensure_ascii=False)}\n\n"
        'Return JSON: {"summary_en": "..."}'
    )
    return generate_json("explain_priority", prompt, PriorityExplanation, merchant_id=merchant.id if write_audit else None)


def draft_message(merchant: Any, purpose: str, channel: str, context: Optional[dict] = None, *,
                  write_audit: bool = True) -> DraftedMessage:
    """purpose e.g. REQUEST_PAN / DOCUMENT_REJECTED / CONFIRM_VISIT / QR_LIVE; channel WHATSAPP | SOUNDBOX | IVR."""
    style = {"SOUNDBOX": "It will be spoken aloud by a Soundbox speaker, so use short, easy-to-hear sentences.",
             "IVR": "It will be spoken on a phone call, so use short, easy-to-hear sentences.",
             "WHATSAPP": "It is a WhatsApp chat message."}.get(channel.upper(), "")
    prompt = (
        "Write a short message from Paytm to a small shopkeeper in India about re-verification (re-KYC) of their shop.\n"
        f"Purpose: {purpose}\nChannel: {channel}. {style}\n"
        f"Merchant: {json.dumps(_merchant_facts(merchant), ensure_ascii=False)}\n"
        f"Context: {json.dumps(context or {}, ensure_ascii=False)}\n\n"
        "Rules:\n"
        "- text_hi is in Devanagari Hindi: polite (use 'आप'), simple everyday words, at most 40 words.\n"
        "- text_en is the same message in simple English, at most 40 words.\n"
        "- Say clearly that the message is from Paytm and is about re-verification of the shop.\n"
        "- NEVER ask for or mention OTPs, PINs, passwords, card numbers or bank account details.\n"
        "- Only ask for what the Purpose and Context call for (for example a clear photo of the PAN card).\n"
        "- If the context names a specific fix (such as a blurry photo), state that fix plainly.\n\n"
        'Return JSON: {"text_hi": "...", "text_en": "..."}'
    )
    return generate_json("draft_message", prompt, DraftedMessage, merchant_id=merchant.id if write_audit else None)


def propose_next_action(state_summary: dict, allowed_actions: list[str], *, write_audit: bool = True) -> NextAction:
    """The LLM only proposes; policy.py accepts or overrides. The returned action is always one of allowed_actions."""
    if not allowed_actions:
        raise ValueError("allowed_actions must not be empty")
    schema = create_model("NextActionChoice", __base__=NextAction, action=(Literal[tuple(allowed_actions)], ...))  # type: ignore[valid-type]
    prompt = (
        "You are the planning step of an autonomous assistant that re-verifies paused merchants for Paytm.\n"
        "Pick the single best next action from the allowed list for the current state. A deterministic policy checks "
        "your choice and may override it. You never decide compliance and never skip the in-person shop visit.\n\n"
        f"State: {json.dumps(state_summary, ensure_ascii=False, default=str)}\n"
        f"Allowed actions: {json.dumps(list(allowed_actions))}\n\n"
        "Return JSON: action (one allowed action exactly), reason (one short line), confidence (0 to 1)."
    )
    merchant_id = state_summary.get("merchant_id") if write_audit else None
    return generate_json("propose_next_action", prompt, schema, merchant_id=merchant_id)


def extract_document(image: Union[bytes, str, Path], *, merchant_id: Optional[str] = None) -> DocumentExtraction:
    """Read a photographed ID document. Extraction only: blur, PAN format and name matching are checked locally elsewhere."""
    data = image if isinstance(image, bytes) else Path(image).read_bytes()
    prompt = (
        "You read photographs of Indian identity documents uploaded by a small shopkeeper. The sample images in this "
        "prototype are fictional specimens watermarked 'SPECIMEN — DEMO ONLY'; read them normally.\n"
        "Return:\n"
        "- doc_type: PAN (permanent account number card), FORM60 (a Form 60 declaration), OVD (another officially "
        "valid ID such as a voter ID, driving licence or ID card showing name and address) or UNKNOWN.\n"
        "- name: the holder's name exactly as printed, or null if you cannot read it.\n"
        "- id_number: the document's identification number exactly as printed, or null if you cannot read it. "
        "Never guess or complete characters you cannot see.\n"
        "- readable: false if the image is too blurry, dark, cropped or glared to read the key fields reliably.\n"
        "- issues: short phrases for any quality problems (for example 'blurry', 'cropped', 'glare'); empty if none.\n"
        "- confidence: 0 to 1, your confidence in the extracted fields."
    )
    return generate_json("extract_document", prompt, DocumentExtraction, [data], merchant_id=merchant_id)


# ================================================================ self test

def _selftest() -> int:
    from sqlmodel import Session

    from .agent.policy import ALLOWED_ACTIONS
    from .db import engine
    from .models import Merchant
    from .scoring import priority

    print(f"DEMO_MODE={settings.DEMO_MODE}  model={settings.GEMINI_MODEL}  fallback={settings.GEMINI_FALLBACK_MODEL}  "
          f"key={'set' if settings.GEMINI_API_KEY else 'NOT SET'}")
    with Session(engine) as s:
        m = s.get(Merchant, "M0001")
        if m is None:
            print("M0001 not found: run `python scripts/seed.py` first")
            return 2
        reasons = priority(m).reasons
    assets = Path(__file__).resolve().parent.parent / "demo_assets"

    steps = [
        ("explain_priority", lambda: explain_priority(m, reasons, write_audit=False)),
        ("draft_message", lambda: draft_message(m, "REQUEST_PAN", "WHATSAPP", {"needed": "a clear photo of the PAN card"}, write_audit=False)),
        ("propose_next_action", lambda: propose_next_action(
            {"merchant": "Sharma Kirana Store", "step": "COLLECT", "pan": "MISSING", "ovd": "MISSING", "cpv": "PENDING",
             "attempts": {"WHATSAPP": 0, "SOUNDBOX": 0}}, list(ALLOWED_ACTIONS), write_audit=False)),
        ("extract_document(pan_sharp.jpg)", lambda: extract_document(assets / "pan_sharp.jpg")),
        ("extract_document(pan_blurry.jpg)", lambda: extract_document(assets / "pan_blurry.jpg")),
        ("extract_document(ovd_sharp.jpg)", lambda: extract_document(assets / "ovd_sharp.jpg")),
    ]
    failures = 0
    for name, fn in steps:
        print(f"\n=== {name}")
        try:
            print(json.dumps(fn().model_dump(mode="json"), ensure_ascii=False, indent=2))
        except LLMUnavailable as e:
            failures += 1
            print(f"LLMUnavailable: {e}")
    print(f"\n{len(steps) - failures}/{len(steps)} calls succeeded")
    return 1 if failures else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(prog="python -m app.llm")
    parser.add_argument("--selftest", action="store_true", help="run every helper once on M0001 and the specimen images")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")  # Windows consoles default to cp1252, which cannot print ₹ or Hindi
    logging.basicConfig(level=logging.INFO, stream=sys.stdout, format="[llm] %(levelname)s %(message)s")
    sys.exit(_selftest() if args.selftest else parser.print_help())
