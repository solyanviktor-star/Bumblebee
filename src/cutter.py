"""FFmpeg обрезка клипа по [start, end] в секундах.

Перекодируем (re-encode), а не -c copy: yarn-клипы короткие, а -ss перед -i на keyframes
даёт неточный старт на сотни миллисекунд. Точность важнее скорости.
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
    """Вырезать [start, end] из src в dst.

    Audio fade in/out короткий по умолчанию (убирает щелчки между склейками).
    Если is_sentence_end=True — fade-out длиннее, даёт естественную паузу-передышку
    на границе предложений в финальном ролике.
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
