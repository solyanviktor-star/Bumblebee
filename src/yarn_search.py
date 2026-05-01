"""Search getyarn.io for a phrase via curl_cffi with a Chrome TLS fingerprint.

Faster and more reliable than Playwright: HTTP-only, no persistent browser
to throttle, and Cloudflare lets it through cleanly.

A single yarn-find HTTP page caps at 20 clips, but the public site exposes
faceted filters (decades, rateds, genres) that together surface a much
larger fraction of the real catalogue. When the base call hits the 20-clip
ceiling we fan out to those facets in parallel and merge the results, which
typically grows the pool 3-5x for popular words.
"""
from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import quote

from curl_cffi import requests as curl_requests

_CLIP_ID_RE = re.compile(r"yarn-clip/([a-f0-9-]{36})", re.IGNORECASE)
_BASE = "https://getyarn.io/yarn-find?text="
_HEADERS = {
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# Facets discovered on the public yarn-find page. Each value is its own
# 20-clip slice with substantial overlap with the base call but enough new
# ids to make it worth fanning out. Costs ~22 HTTP requests in parallel
# (~2-5s wall clock) once per phrase per process — cached afterwards.
_FACET_DECADES = ("1980", "1990", "2000", "2010", "2020")
_FACET_RATEDS = ("PG", "PG-13", "R", "TV-14", "TV-MA", "TV-PG", "N/A")
_FACET_GENRES = (
    "Action", "Adventure", "Animation", "Comedy", "Crime",
    "Drama", "Fantasy", "Mystery", "Sci-Fi", "Short",
)

# Per-process cache so each phrase hits yarn only once even when the same
# chunk recurs across many variants in mix mode.
_SEARCH_CACHE: dict[str, list[str]] = {}


def _parse_clip_ids(html: str) -> list[str]:
    """Extract distinct yarn clip UUIDs from a yarn-find HTML page in document order."""
    ids: list[str] = []
    seen: set[str] = set()
    for m in _CLIP_ID_RE.finditer(html):
        cid = m.group(1).lower()
        if cid not in seen:
            seen.add(cid)
            ids.append(cid)
    return ids


def _fetch(url: str, attempts: int = 3) -> list[str]:
    """Single yarn HTTP request -> clip ids. Retries on timeout to ride
    through Cloudflare throttling. Returns empty list after final failure."""
    import time as _t
    for n in range(attempts):
        try:
            r = curl_requests.get(url, impersonate="chrome", headers=_HEADERS, timeout=12)
        except Exception:
            _t.sleep(0.5 * (n + 1))
            continue
        if r.status_code != 200:
            return []
        return _parse_clip_ids(r.text)
    return []


def _facet_urls(phrase: str) -> list[str]:
    """All faceted URL variants for one phrase."""
    encoded = quote(phrase)
    base = f"https://getyarn.io/yarn-find?text={encoded}&limit=48"
    urls = [f"{base}&decades={d}" for d in _FACET_DECADES]
    urls += [f"{base}&rateds={quote(r)}" for r in _FACET_RATEDS]
    urls += [f"{base}&genres={quote(g)}" for g in _FACET_GENRES]
    return urls


class YarnSearch:
    """Context-manager-shaped, kept that way so callers don't have to change."""

    def __init__(self, headless: bool = True):
        # The headless arg is kept for backwards compatibility; ignored here.
        pass

    def __enter__(self) -> "YarnSearch":
        return self

    def __exit__(self, *exc):
        pass

    def probe_count(self, phrase: str) -> int:
        """Cheap rarity probe: returns the size of yarn's first-page pool
        for a phrase, capped at 20.

        Use this when you only need to decide rare-vs-common — e.g. to
        force a single-word chunk in greedy splitting. A single HTTP call
        per word, no facet fan-out, no cache write (so `.search()` can
        still do its full expansion later if needed).
        """
        url = _BASE + quote(phrase)
        return len(_fetch(url, attempts=2))

    def search(self, phrase: str, max_results: int = 200) -> list[str]:
        """Return clip_ids for the phrase. Empty list = nothing matched.

        Strategy: one base HTTP call. If that hits the 20-clip page ceiling,
        fan out across decade/rated/genre facets in parallel and union the
        results to get up to ~100 unique clips for popular words. Pool size
        is capped at `max_results`; results are cached per phrase per process.
        """
        cached = _SEARCH_CACHE.get(phrase)
        if cached is not None:
            return cached[:max_results]

        base_url = _BASE + quote(phrase)
        base_ids = _fetch(base_url)

        # Small pool — facet fan-out won't add anything meaningful. Skip the
        # extra ~22 requests entirely.
        if len(base_ids) < 20:
            _SEARCH_CACHE[phrase] = base_ids
            return base_ids[:max_results]

        # Large pool likely capped at 20 by the page renderer; expand it.
        # max_workers=3 stays under yarn/Cloudflare's silent connection
        # throttle (which kicks in around 5+ simultaneous requests from
        # the same IP) and finishes the 22-URL fan-out in ~10-15s.
        merged: list[str] = list(base_ids)
        seen: set[str] = set(base_ids)
        with ThreadPoolExecutor(max_workers=3) as pool:
            futures = [pool.submit(_fetch, u) for u in _facet_urls(phrase)]
            for fut in as_completed(futures):
                for cid in fut.result():
                    if cid not in seen:
                        seen.add(cid)
                        merged.append(cid)

        _SEARCH_CACHE[phrase] = merged
        return merged[:max_results]
