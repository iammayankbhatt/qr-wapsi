"""Serves Soundbox clips: /api/audio/{key}.wav (key = sha256(text + speaker), see voice.py)."""
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from .. import voice

router = APIRouter()


@router.get("/{key}.wav")
def audio_clip(key: str):
    path = voice.audio_path(key)  # validates the key: 64 hex chars, no paths
    if path is None:
        raise HTTPException(404, "audio clip not found")
    return FileResponse(path, media_type="audio/wav", headers={"Cache-Control": "public, max-age=86400, immutable"})
