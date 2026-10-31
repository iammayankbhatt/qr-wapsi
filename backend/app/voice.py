"""Hindi text-to-speech for the Soundbox (Sarvam bulbul:v3), with the same demo-cache rules as llm.py.

synthesize(text) -> audio_ref (the cache key) or None. The clip is served at /api/audio/{audio_ref}.wav.
  * key = sha256(text + speaker)
  * DEMO_MODE: live   = call Sarvam, keep the clip in data/audio/ (runtime files, not the demo cache)
               record = call Sarvam, save the clip to demo_cache/audio/
               replay = never call Sarvam; serve demo_cache/audio/ only (a miss is logged loudly)
  * no key, a timeout or any API error -> None, and the SoundboxWidget speaks with the browser's hi-IN voice.
"""
import argparse
import base64
import hashlib
import logging
import re
import sys
import time
from pathlib import Path
from typing import Optional

import httpx

from .config import settings

log = logging.getLogger("qrwapsi.voice")

SARVAM_URL = "https://api.sarvam.ai/text-to-speech"
MODEL = "bulbul:v3"
SPEAKER = "priya"
LANGUAGE = "hi-IN"
TIMEOUT_S = 15
ATTEMPTS = 2  # first try + 1 retry on transient errors
BACKOFF_S = 0.5
KEY_RE = re.compile(r"^[0-9a-f]{64}$")

_sleep = time.sleep  # patched in tests


def audio_key(text: str, speaker: str = SPEAKER) -> str:
    return hashlib.sha256((text + speaker).encode("utf-8")).hexdigest()


def _cache_dir() -> Path:
    return settings.DEMO_CACHE_DIR / "audio"


def _runtime_dir() -> Path:
    return settings.DATA_DIR / "audio"


def audio_path(key: str) -> Optional[Path]:
    """The clip file for a key (demo cache first, then runtime clips), or None."""
    if not KEY_RE.match(key):
        return None
    for d in (_cache_dir(), _runtime_dir()):
        p = d / f"{key}.wav"
        if p.is_file():
            return p
    return None


def _call_sarvam(text: str, speaker: str) -> bytes:
    """One request; returns WAV bytes. Tests replace this."""
    r = httpx.post(SARVAM_URL, timeout=TIMEOUT_S, headers={"api-subscription-key": settings.SARVAM_API_KEY},
                   json={"text": text, "language_code": LANGUAGE, "model": MODEL, "speaker": speaker,
                         "output_audio_codec": "wav"})
    r.raise_for_status()
    audio = base64.b64decode(r.json()["audios"][0])
    if audio[:4] != b"RIFF" or audio[8:12] != b"WAVE":
        raise ValueError("Sarvam did not return a WAV file")
    return audio


def _transient(e: Exception) -> bool:
    if isinstance(e, httpx.HTTPStatusError):
        return e.response.status_code in (408, 429) or e.response.status_code >= 500
    return isinstance(e, httpx.TransportError)


def synthesize(text: str, speaker: str = SPEAKER) -> Optional[str]:
    """audio_ref for `text`, or None when no clip is available (the browser voice is used instead)."""
    text = (text or "").strip()
    if not text:
        return None
    key = audio_key(text, speaker)
    mode = settings.DEMO_MODE

    if mode == "replay":
        if (_cache_dir() / f"{key}.wav").is_file():
            log.info("TTS key=%s cache_hit=True mode=replay", key[:12])
            return key
        log.warning("!!! REPLAY AUDIO CACHE MISS key=%s text=%r — no TTS call in replay mode; the Soundbox will use "
                    "the browser voice. Run scripts/warm_cache.py with DEMO_MODE=record.", key[:12], text[:60])
        return None

    if not settings.SARVAM_API_KEY:
        log.warning("SARVAM_API_KEY is not set; the Soundbox will use the browser voice")
        return None
    started = time.perf_counter()
    for attempt in range(ATTEMPTS):
        try:
            audio = _call_sarvam(text, speaker)
            break
        except Exception as e:  # noqa: BLE001  (any failure: retry if transient, else browser voice)
            log.warning("Sarvam TTS failed attempt=%d/%d: %s", attempt + 1, ATTEMPTS, str(e)[:200])
            if attempt == ATTEMPTS - 1 or not _transient(e):
                return None
            _sleep(BACKOFF_S)
    folder = _cache_dir() if mode == "record" else _runtime_dir()
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{key}.wav").write_bytes(audio)
    log.info("TTS key=%s bytes=%d latency=%dms mode=%s", key[:12], len(audio), (time.perf_counter() - started) * 1000, mode)
    return key


if __name__ == "__main__":
    parser = argparse.ArgumentParser(prog="python -m app.voice", description="Synthesize one Hindi line and print its audio_ref")
    parser.add_argument("text")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.INFO, stream=sys.stdout, format="[voice] %(levelname)s %(message)s")
    ref = synthesize(args.text)
    print(ref or "no clip (browser voice will be used)")
