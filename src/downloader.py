"""Скачка mp4 клипа yarn.co по clip_id.

CF на y.yarn.co режет httpx по TLS-fingerprint. curl_cffi с impersonate='chrome'
ставит TLS как у настоящего Chrome — проходит без всяких challenge-кукисов.
"""
from __future__ import annotations

from pathlib import Path

from curl_cffi import requests as curl_requests

_BASE = "https://y.yarn.co/{}.mp4?v=0"
_HEADERS = {
    "Referer": "https://getyarn.io/",
    "Accept": "video/webm,video/ogg,video/*;q=0.9,application/ogg;q=0.7,audio/*;q=0.6,*/*;q=0.5",
    "Accept-Language": "en-US,en;q=0.9",
}


def download_clip(clip_id: str, cache_dir: Path) -> Path:
    """Скачать клип в cache_dir, вернуть путь. Если уже есть — пропустить."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    target = cache_dir / f"{clip_id}.mp4"
    if target.exists() and target.stat().st_size > 1024:
        return target

    url = _BASE.format(clip_id)
    r = curl_requests.get(url, impersonate="chrome", headers=_HEADERS, timeout=60)
    if r.status_code != 200:
        raise RuntimeError(f"yarn download failed: {r.status_code} for {clip_id}")
    if not r.content or len(r.content) < 1024:
        raise RuntimeError(f"yarn returned empty body for {clip_id}")
    target.write_bytes(r.content)
    return target
