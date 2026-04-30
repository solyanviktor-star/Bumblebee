"""FFmpeg cut by [start, end] in seconds.

We re-encode rather than -c copy: yarn clips are short, and -ss before -i
only seeks to the nearest keyframe, drifting hundreds of milliseconds.
Accuracy beats speed here.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path


def _ffmpeg_bin() -> str:
    return os.environ.get("FFMPEG_BIN", "ffmpeg")


def cut(
    src: Path,
    start: float,
    end: float,
    dst: Path,
    is_sentence_end: bool = False,
) -> Path:
    """Cut [start, end] from src into dst.

    Audio fade in/out is short by default (kills clicks at splice boundaries).
    When is_sentence_end=True the fade-out is longer, giving a natural breathing
    pause at sentence boundaries in the final reel.
    """
    duration = max(0.05, end - start)
    dst.parent.mkdir(parents=True, exist_ok=True)

    fade_in = 0.012
    fade_out = 0.18 if is_sentence_end else 0.025
    fade_out_start = max(0.0, duration - fade_out)
    afilter = (
        f"afade=t=in:st=0:d={fade_in:.3f},"
        f"afade=t=out:st={fade_out_start:.3f}:d={fade_out:.3f}"
    )

    cmd = [
        _ffmpeg_bin(), "-y",
        "-ss", f"{start:.3f}",
        "-i", str(src),
        "-t", f"{duration:.3f}",
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "18",
        "-af", afilter,
        "-c:a", "aac",
        "-b:a", "192k",
        "-movflags", "+faststart",
        str(dst),
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return dst
