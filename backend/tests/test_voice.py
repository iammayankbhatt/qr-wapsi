"""voice.py: Sarvam TTS with demo-cache rules, the /api/audio route, and the Soundbox tool using it."""
import base64

import httpx
import pytest
from fastapi.testclient import TestClient

from app import voice
from app.main import app
from app.tools import play_soundbox_prompt

WAV = b"RIFF\x24\x00\x00\x00WAVEfmt " + b"\x00" * 28


class FakeSarvam:
    def __init__(self):
        self.calls = []
        self.script = []  # exceptions or bytes, consumed in order; default: a WAV

    def __call__(self, text, speaker):
        self.calls.append(text)
        item = self.script.pop(0) if self.script else WAV
        if isinstance(item, Exception):
            raise item
        return item


@pytest.fixture
def fake(monkeypatch, tmp_path):
    f = FakeSarvam()
    monkeypatch.setattr(voice, "_call_sarvam", f)
    monkeypatch.setattr(voice, "_sleep", lambda s: None)
    monkeypatch.setattr(voice.settings, "DEMO_CACHE_DIR", tmp_path / "demo_cache")
    monkeypatch.setattr(voice.settings, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(voice.settings, "SARVAM_API_KEY", "test-key")
    return f


def http_error(code):
    return httpx.HTTPStatusError("x", request=httpx.Request("POST", voice.SARVAM_URL), response=httpx.Response(code))


def test_key_is_sha256_of_text_plus_speaker():
    assert voice.audio_key("नमस्ते") == voice.audio_key("नमस्ते", "priya") != voice.audio_key("नमस्ते", "anushka")
    assert len(voice.audio_key("x")) == 64


def test_record_saves_to_demo_cache_and_replay_serves_it_without_calling(fake, monkeypatch, tmp_path):
    monkeypatch.setattr(voice.settings, "DEMO_MODE", "record")
    key = voice.synthesize("आपका QR फिर से चालू। धन्यवाद!")
    assert (tmp_path / "demo_cache" / "audio" / f"{key}.wav").read_bytes() == WAV
    monkeypatch.setattr(voice.settings, "DEMO_MODE", "replay")
    assert voice.synthesize("आपका QR फिर से चालू। धन्यवाद!") == key
    assert len(fake.calls) == 1
    assert voice.audio_path(key) == tmp_path / "demo_cache" / "audio" / f"{key}.wav"


def test_replay_miss_is_loud_and_never_calls(fake, monkeypatch, caplog):
    monkeypatch.setattr(voice.settings, "DEMO_MODE", "replay")
    assert voice.synthesize("never recorded") is None
    assert fake.calls == []
    assert any("REPLAY AUDIO CACHE MISS" in r.getMessage() for r in caplog.records)


def test_live_mode_keeps_clips_out_of_the_demo_cache(fake, monkeypatch, tmp_path):
    monkeypatch.setattr(voice.settings, "DEMO_MODE", "live")
    key = voice.synthesize("live line")
    assert (tmp_path / "data" / "audio" / f"{key}.wav").exists()
    assert not (tmp_path / "demo_cache" / "audio").exists()


def test_no_key_means_browser_voice(fake, monkeypatch):
    monkeypatch.setattr(voice.settings, "DEMO_MODE", "live")
    monkeypatch.setattr(voice.settings, "SARVAM_API_KEY", "")
    assert voice.synthesize("x") is None and fake.calls == []


def test_transient_error_is_retried_once(fake, monkeypatch):
    monkeypatch.setattr(voice.settings, "DEMO_MODE", "live")
    fake.script = [http_error(503)]
    assert voice.synthesize("x") is not None and len(fake.calls) == 2


@pytest.mark.parametrize("err", [http_error(400), http_error(401), ValueError("not a WAV")])
def test_other_failures_fall_back_to_browser_voice_without_retry(fake, monkeypatch, err):
    monkeypatch.setattr(voice.settings, "DEMO_MODE", "live")
    fake.script = [err]
    assert voice.synthesize("x") is None and len(fake.calls) == 1


def test_real_client_decodes_base64_wav(monkeypatch):
    def post(url, **kw):
        assert kw["headers"] == {"api-subscription-key": "k"}
        assert kw["json"] == {"text": "नमस्ते", "language_code": "hi-IN", "model": "bulbul:v3", "speaker": "priya",
                              "output_audio_codec": "wav"}
        return httpx.Response(200, json={"audios": [base64.b64encode(WAV).decode()]}, request=httpx.Request("POST", url))

    monkeypatch.setattr(voice.settings, "SARVAM_API_KEY", "k")
    monkeypatch.setattr(voice.httpx, "post", post)
    assert voice._call_sarvam("नमस्ते", "priya") == WAV


def test_audio_route_serves_clips_and_rejects_bad_keys(fake, monkeypatch):
    monkeypatch.setattr(voice.settings, "DEMO_MODE", "record")
    key = voice.synthesize("route line")
    with TestClient(app) as c:
        r = c.get(f"/api/audio/{key}.wav")
        assert r.status_code == 200 and r.headers["content-type"] == "audio/wav" and r.content == WAV
        assert c.get(f"/api/audio/{'0' * 64}.wav").status_code == 404
        assert c.get("/api/audio/..%2F..%2Fapp.wav").status_code == 404


def test_soundbox_tool_attaches_a_clip_when_one_exists(fake, monkeypatch):
    monkeypatch.setattr(voice.settings, "DEMO_MODE", "record")
    res = play_soundbox_prompt("M0001", "Paytm सूचना: परीक्षण")
    assert res["ok"] and res["audio_ref"] == voice.audio_key("Paytm सूचना: परीक्षण")
    monkeypatch.setattr(voice.settings, "DEMO_MODE", "replay")
    assert play_soundbox_prompt("M0001", "बिना रिकॉर्ड")["audio_ref"] is None  # browser voice fallback
