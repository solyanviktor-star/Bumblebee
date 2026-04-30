"""Groq Whisper large-v3 с word-level timestamps.

Возвращает список dict{word, start, end} в секундах.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from groq import Groq

_MODEL = "whisper-large-v3"


def transcribe_words(audio_path: Path, cache: bool = True) -> list[dict]:
    """Транскрибировать клип, вернуть [{word, start, end}, ...]. Кэшируется в .json рядом."""
    cache_path = audio_path.with_suffix(".words.json")
    if cache and cache_path.exists():
        return json.loads(cache_path.read_text(encoding="utf-8"))

    client = Groq(api_key=os.environ["GROQ_API_KEY"])
    with audio_path.open("rb") as f:
        resp = client.audio.transcriptions.create(
            file=(audio_path.name, f.read()),
            model=_MODEL,
            response_format="verbose_json",
            timestamp_granularities=["word"],
            language="en",
        )

    words = getattr(resp, "words", None) or resp.get("words", [])
    out = [
        {"word": _normalize(w["word"] if isinstance(w, dict) else w.word),
         "start": float(w["start"] if isinstance(w, dict) else w.start),
         "end":   float(w["end"]   if isinstance(w, dict) else w.end)}
        for w in words
    ]

    if cache:
        cache_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def _normalize(word: str) -> str:
    return word.strip().lower().strip(".,!?;:\"'()[]{}")
