"""FFmpeg cut by [start, end] in seconds.

We re-encode rather than -c copy: yarn clips are short, and -ss before -i
only seeks to the nearest keyframe, drifting hundreds of milliseconds.
Accuracy beats speed here.

We also normalise every cut to a fixed (resolution, fps, pixel format,
sample rate, channels) so that the concat demuxer with -c copy can stitch
parts together without container/codec mismatches. yarn clips arrive with
all sorts of audio sample rates (24/44.1/48 kHz) and frame widths
(854, 864, 1062, 1146 px); without normalisation the concatenated mp4 has
the right metadata but the wrong audio (silence, wrong speed, glitches).
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

# Target output spec — every cut is re-encoded to these parameters so that
# concat -c copy is safe across all chunks.
_TARGET_W = 854
_TARGET_H = 480
_TARGET_FPS = 30
_TARGET_AUDIO_RATE = 48000
_TARGET_AUDIO_CH = 2
_VFILTER = (
    f"scale={_TARGET_W}:{_TARGET_H}:force_original_aspect_ratio=decrease,"
    f"pad={_TARGET_W}:{_TARGET_H}:(ow-iw)/2:(oh-ih)/2:color=black,"
    "setsar=1"
)


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
        "-vf", _VFILTER,
        "-r", str(_TARGET_FPS),
        "-pix_fmt", "yuv420p",
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "18",
        "-af", afilter,
        "-c:a", "aac",
        "-ar", str(_TARGET_AUDIO_RATE),
        "-ac", str(_TARGET_AUDIO_CH),
        "-b:a", "192k",
        "-movflags", "+faststart",
        str(dst),
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return dst
