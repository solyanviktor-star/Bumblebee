"""Поиск фразы на yarn.co (getyarn.io) через curl_cffi с TLS-fingerprint Chrome.

Это быстрее и надёжнее Playwright: один HTTP-запрос на одну фразу, никакого
троттлинга/persistent-browser-износа, проходит Cloudflare без проблем.
"""
from __future__ import annotations

import re
from urllib.parse import quote

from curl_cffi import requests as curl_requests

_CLIP_ID_RE = re.compile(r"yarn-clip/([a-f0-9-]{36})", re.IGNORECASE)
_BASE = "https://getyarn.io/yarn-find?text="
_HEADERS = {
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


class YarnSearch:
    """Сохраняем интерфейс контекст-менеджера, чтобы не ломать вызывающий код."""

    def __init__(self, headless: bool = True):
        # параметр headless оставлен для совместимости — тут он игнорируется
        pass

    def __enter__(self) -> "YarnSearch":
        return self

    def __exit__(self, *exc):
        pass

    def search(self, phrase: str, max_results: int = 20) -> list[str]:
        """Список clip_id для фразы. Пусто = ничего не нашлось."""
        url = _BASE + quote(phrase)
        try:
            r = curl_requests.get(url, impersonate="chrome", headers=_HEADERS, timeout=30)
        except Exception:
            return []
        if r.status_code != 200:
            return []

        ids: list[str] = []
        seen: set[str] = set()
        for m in _CLIP_ID_RE.finditer(r.text):
            cid = m.group(1).lower()
            if cid not in seen:
                seen.add(cid)
                ids.append(cid)
                if len(ids) >= max_results:
                    break
        return ids
