"""Greedy longest-match splitter.

Algorithm:
    i = 0
    while i < len(words):
        for chunk_len in range(min(MAX_CHUNK, n - i), 0, -1):
            chunk = words[i : i + chunk_len]
            if a clip exists where this exact subsequence is spoken in order:
                take it, i += chunk_len, break
        else:
            # single word not found anywhere -> skip
            i += 1

"Found a clip" means yarn.co returned candidates, we downloaded + transcribed
+ word_matcher returned score == 1.0 (every word of the chunk in order).
"""
from __future__ import annotations

import os
import random
import re
from dataclasses import dataclass
from pathlib import Path

from .downloader import download_clip
from .transcriber import transcribe_words
from .word_matcher import find_phrase
from .yarn_search import YarnSearch

_TOKEN_RE = re.compile(r"[A-Za-z0-9']+")

# Global set of excluded clip_ids — used to generate non-overlapping variants.
# Populated externally via add_excluded() / reset_excluded().
_EXCLUDED: set[str] = set()


def add_excluded(ids) -> None:
    _EXCLUDED.update(ids)


def reset_excluded() -> None:
    _EXCLUDED.clear()


def _excluded_ids() -> set[str]:
    return _EXCLUDED


@dataclass
class Chunk:
    text: str
    clip_id: str
    mp4: Path
    start: float
    end: float


def _tokenize(phrase: str) -> list[str]:
    return _TOKEN_RE.findall(phrase)


def _check_candidate(clip_id: str, text: str, cache_dir: Path) -> Chunk | None:
    """Download + transcribe + match a single clip. Returns None if it doesn't fit.
    Any error is logged so we never silently skip a candidate."""
    try:
        mp4 = download_clip(clip_id, cache_dir)
        words = transcribe_words(mp4)
        match = find_phrase(words, text)
    except Exception as e:
        print(f"        ! candidate {clip_id[:8]}: {type(e).__name__}: {e}")
        return None
    if match is not None and match.score >= 1.0:
        return Chunk(text=text, clip_id=clip_id, mp4=mp4, start=match.start, end=match.end)
    return None


def _try_chunk(
    chunk_words: list[str],
    yarn: YarnSearch,
    cache_dir: Path,
    max_candidates: int = 8,
) -> Chunk | None:
    """Is there a clip where this subsequence is spoken in order?
    We iterate candidates serially — return on the first exact match.

    If env var BUMBLEBEE_SHUFFLE=1 is set, candidates are shuffled randomly,
    which lets the same phrase produce different cuts across variants.
    """
    text = " ".join(chunk_words)
    clip_ids = yarn.search(text, max_results=max_candidates)
    if not clip_ids:
        print(f"        . yarn: 0 ids for {text!r}")
        return None
    if os.environ.get("BUMBLEBEE_SHUFFLE") == "1":
        random.shuffle(clip_ids)
    # Skip clip_ids already used in previous variants (mix-mode).
    # If everything is excluded, fall back to the unfiltered list.
    excluded = _excluded_ids()
    if excluded:
        filtered = [c for c in clip_ids if c not in excluded]
        if filtered:
            clip_ids = filtered
    print(f"        . yarn: {len(clip_ids)} ids for {text!r}")

    for clip_id in clip_ids:
        result = _check_candidate(clip_id, text, cache_dir)
        if result is None:
            # log what the transcript actually contained — useful for debugging
            try:
                mp4 = download_clip(clip_id, cache_dir)
                words = transcribe_words(mp4)
                t = " ".join(w["word"] for w in words)
                print(f"        . {clip_id[:8]} no-match. transcript: {t!r}")
            except Exception as e:
                print(f"        . {clip_id[:8]} debug-log fail: {e}")
        else:
            return result
    return None


def greedy_split(
    phrase: str,
    yarn: YarnSearch,
    cache_dir: Path,
    max_chunk: int = 6,
    on_step=None,
) -> tuple[list[Chunk], list[str]]:
    """Return (matched chunks in order, words that had to be skipped).

    on_step(stage, **kwargs) is an optional progress callback.
    """
    words = _tokenize(phrase)
    chunks: list[Chunk] = []
    skipped: list[str] = []

    i = 0
    n = len(words)
    while i < n:
        max_len = min(max_chunk, n - i)
        found: Chunk | None = None
        for L in range(max_len, 0, -1):
            chunk_words = words[i : i + L]
            if on_step:
                on_step("try", text=" ".join(chunk_words))
            found = _try_chunk(chunk_words, yarn, cache_dir)
            if found is not None:
                if on_step:
                    on_step("hit", chunk=found)
                chunks.append(found)
                i += L
                break
        if found is None:
            if on_step:
                on_step("skip", word=words[i])
            skipped.append(words[i])
            i += 1

    return chunks, skipped
