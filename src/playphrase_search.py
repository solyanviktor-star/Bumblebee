"""playphrase.me search via Playwright (the only working route).

Background:
    playphrase.me's anti-forgery layer cannot be replayed from raw HTTP. The
    site's `check-bot.min.js` inspects `navigator.webdriver`, the User-Agent
    for "HeadlessChrome", `navigator.plugins.length`, `navigator.languages`,
    and the WebGL renderer. Even when those checks pass and we send the
    correct CSRF token + cookies, a `fetch()` call from `page.evaluate()`
    still 403s ("Old page, reload"). The only path that the server accepts
    is one driven by the SPA's own router, so we navigate to
    `/#/search?q=PHRASE` and read back the API response that the SPA fires.

What you get:
    The API returns clips with millisecond word-level timestamps already
    attached, so playphrase clips bypass the faster-whisper step entirely:
    we write the timestamps to the same `*.words.json` cache format that
    the rest of the pipeline expects, then download the mp4 from the
    Wasabi S3 CDN with curl_cffi (S3 is open — no auth required).

Pool sizes (sample):
    yarn ceiling per phrase ~20. playphrase per phrase: 23 ("greedily"),
    40 ("Gradient"), 131 ("I am your father"), 5826 ("open the door"),
    73539 ("open"). Order of magnitude bigger pool, especially for rare
    words and short phrases.
"""
from __future__ import annotations

import json
import time
import urllib.parse
from dataclasses import dataclass
from pathlib import Path

from curl_cffi import requests as curl_requests

# Patch navigator.* at every page so check-bot.min.js doesn't classify us as a bot.
_STEALTH_INIT = """
Object.defineProperty(navigator, 'webdriver', {get: () => false});
Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
window.chrome = {runtime: {}};
"""

# Pretending to be a non-headless Chrome avoids the "HeadlessChrome" UA check.
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36"
)


@dataclass
class PlayPhraseClip:
    """One playphrase result, ready for the rest of the pipeline.

    `text` is the spoken text on screen, `words` is a list of
    {word, start, end} entries in seconds (already cut to clip-relative
    times by `_normalize_words`). `clip_id` is a stable, filesystem-safe
    identifier we mint for caching.
    """
    clip_id: str
    text: str
    movie: str
    video_url: str
    words: list[dict]


class PlayPhraseSearch:
    """Context-manager wrapper around a single Playwright Chromium session.

    Open it once, run many searches; the bootstrap navigation costs ~10s
    and each subsequent `search()` is sub-second.
    """

    def __init__(self):
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None

    def __enter__(self) -> "PlayPhraseSearch":
        from playwright.sync_api import sync_playwright

        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"],
        )
        self._context = self._browser.new_context(user_agent=_UA)
        self._context.add_init_script(_STEALTH_INIT)
        self._page = self._context.new_page()
        # Bootstrap — load the SPA so subsequent searches navigate cheaply.
        self._page.goto(
            "https://www.playphrase.me/",
            wait_until="networkidle",
            timeout=30000,
        )
        return self

    def __exit__(self, *exc):
        try:
            if self._browser:
                self._browser.close()
        finally:
            if self._playwright:
                self._playwright.stop()

    def search(self, phrase: str, max_results: int = 5) -> list[PlayPhraseClip]:
        """Return up to `max_results` clips matching the phrase.

        playphrase returns 5 per request by default. `max_results > 5`
        is currently silently capped at 5 — paginating the SPA via the URL
        is non-trivial and 5 results per phrase already exceeds yarn's
        ceiling for most rare words.
        """
        encoded = urllib.parse.quote(phrase)
        target = f"https://www.playphrase.me/#/search?q={encoded}"
        try:
            with self._page.expect_response(
                lambda r: (
                    "/api/v1/phrases/search?" in r.url
                    and f"q={encoded}" in r.url
                    and r.status == 200
                ),
                timeout=15000,
            ) as info:
                self._page.goto(target)
            resp = info.value
            data = resp.json()
        except Exception:
            return []

        out: list[PlayPhraseClip] = []
        for ph in data.get("phrases", [])[:max_results]:
            video_url = ph.get("video-url")
            if not video_url:
                continue
            text = (ph.get("text") or "").strip()
            movie = (ph.get("video-info") or {}).get("info", "") or ""
            words = _normalize_words(ph.get("words") or [])
            clip_id = _mint_clip_id(video_url, ph.get("id") or ph.get("start", 0))
            out.append(
                PlayPhraseClip(
                    clip_id=clip_id,
                    text=text,
                    movie=movie,
                    video_url=video_url,
                    words=words,
                )
            )
        return out


def _normalize_words(api_words: list[dict]) -> list[dict]:
    """Convert API word entries into the same shape transcriber.py emits.

    The API gives `start` and `end` in milliseconds and a `text` field
    that may carry trailing punctuation. Word matcher already strips
    punctuation, so we lowercase + strip here and convert to seconds.
    """
    out: list[dict] = []
    for w in api_words:
        text = (w.get("text") or "").strip().lower().strip(".,!?;:\"'()[]{}")
        if not text:
            continue
        start = float(w.get("start", 0)) / 1000.0
        end = float(w.get("end", 0)) / 1000.0
        out.append({"word": text, "start": start, "end": end})
    return out


def _mint_clip_id(video_url: str, salt) -> str:
    """Stable short ID derived from the S3 key + salt.

    Looks like `pp_<8 hex>` so the rest of the pipeline (which displays
    `clip_id[:8]`) keeps producing recognisable identifiers without
    confusing them for yarn UUIDs.
    """
    import hashlib

    h = hashlib.sha1(f"{video_url}|{salt}".encode("utf-8")).hexdigest()
    return f"pp_{h[:8]}"


def cache_clip(clip: PlayPhraseClip, cache_dir: Path) -> Path | None:
    """Download the mp4 and write the words.json so the rest of the
    pipeline picks the clip up via its existing local-cache scan.

    Returns the mp4 path, or None on download failure.
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    mp4_path = cache_dir / f"{clip.clip_id}.mp4"
    words_path = cache_dir / f"{clip.clip_id}.words.json"

    if mp4_path.exists() and mp4_path.stat().st_size > 1024:
        # Idempotent — refresh the words file if missing
        if not words_path.exists():
            words_path.write_text(
                json.dumps(clip.words, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        return mp4_path

    # Wasabi S3 is open; no auth, no anti-bot. Plain GET works.
    try:
        r = curl_requests.get(clip.video_url, impersonate="chrome", timeout=60)
    except Exception as e:
        print(f"        ! pp download failed for {clip.clip_id}: {e}")
        return None
    if r.status_code != 200 or len(r.content) < 1024:
        print(
            f"        ! pp download bad response {r.status_code} "
            f"({len(r.content)} bytes) for {clip.clip_id}"
        )
        return None
    mp4_path.write_bytes(r.content)
    words_path.write_text(
        json.dumps(clip.words, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return mp4_path
