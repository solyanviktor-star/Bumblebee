"""Склейка нескольких mp4 через FFmpeg concat demuxer.

Куски уже перекодированы в одном кодеке (см. cutter.py), так что -c copy безопасен.
"""
from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path


def _ffmpeg_bin() -> str:
    return os.environ.get("FFMPEG_BIN", "ffmpeg")


def concat(parts: list[Path], dst: Path) -> Path:
    if not parts:
        raise ValueError("Нет кусков для склейки")
    dst.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as f:
        for p in parts:
            # FFmpeg concat list: пути в одинарных кавычках, экранировать backslash
            safe = str(p.resolve()).replace("\\", "/").replace("'", r"'\''")
            f.write(f"file '{safe}'\n")
        list_path = f.name

    cmd = [
        _ffmpeg_bin(), "-y",
        "-f", "concat", "-safe", "0",
        "-i", list_path,
        "-c", "copy",
        "-movflags", "+faststart",
        str(dst),
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True)
    finally:
        Path(list_path).unlink(missing_ok=True)
    return dst
