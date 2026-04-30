"""Local word-level transcription powered by faster-whisper.

Returns a list of dicts {word, start, end} in seconds. Runs entirely offline:
no API keys, no network calls. The model weights download once on first use
(~244 MB for small.en) into the HuggingFace cache.

Environment variables (all optional):
    WHISPER_MODEL         Model name. Default: "small.en".
                          Other good options: "base.en" (faster, less accurate),
                          "medium.en" (slower, more accurate).
    WHISPER_DEVICE        "cpu" (default) or "cuda".
    WHISPER_COMPUTE_TYPE  Quantization. "int8" on cpu, "float16" on cuda by default.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from threading import Lock

_MODEL = None
_MODEL_LOCK = Lock()


def _get_model():
    global _MODEL
    if _MODEL is not None:
        return _MODEL
    with _MODEL_LOCK:
        if _MODEL is None:
            from faster_whisper import WhisperModel

            model_name = os.environ.get("WHISPER_MODEL", "small.en")
            device = os.environ.get("WHISPER_DEVICE", "cpu")
            compute_type = os.environ.get(
                "WHISPER_COMPUTE_TYPE",
                "float16" if device == "cuda" else "int8",
            )
            _MODEL = WhisperModel(model_name, device=device, compute_type=compute_type)
    return _MODEL


def transcribe_words(audio_path: Path, cache: bool = True) -> list[dict]:
    """Transcribe a clip and return [{word, start, end}, ...].

    Result is cached to a sibling .words.json next to the audio file.
    """
    cache_path = audio_path.with_suffix(".words.json")
    if cache and cache_path.exists():
        return json.loads(cache_path.read_text(encoding="utf-8"))

    model = _get_model()
    segments, _info = model.transcribe(
        str(audio_path),
        language="en",
        word_timestamps=True,
        vad_filter=False,
        beam_size=5,
    )

    out: list[dict] = []
    for seg in segments:
        if not seg.words:
            continue
        for w in seg.words:
            out.append({
                "word": _normalize(w.word),
                "start": float(w.start),
                "end": float(w.end),
            })

    if cache:
        cache_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def _normalize(word: str) -> str:
    return word.strip().lower().strip(".,!?;:\"'()[]{}")
