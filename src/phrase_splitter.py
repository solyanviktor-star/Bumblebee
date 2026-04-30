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

Optimisations on top of the base algorithm:
- Local-cache-first: every cached transcript is scanned for the target phrase
  before we hit yarn. A clip downloaded for one chunk is therefore reusable
  for any other chunk whose words happen to appear in its transcript.
- Negative cache: phrases that yielded zero exact matches anywhere are not
  re-attempted within the same process — cuts redundant network and Whisper work.
- Wide candidate fan-out: we ask yarn for the maximum 20 ids per phrase
  (yarn caps any single search at 20).
"""
from __future__ import annotations

import json
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

# Phrases that previously failed to match anywhere — cached per process to avoid
# redoing the same fruitless yarn + transcribe round-trips on later variants.
_NEGATIVE_CACHE: set[str] = set()

# Optional second source. When set (via set_playphrase), greedy queries it
# after yarn exhausts a chunk. playphrase clips arrive with word-level
# timestamps from the API itself, so they don't need a faster-whisper pass.
_PLAYPHRASE = None


def set_playphrase(pp) -> None:
    """Register a PlayPhraseSearch instance as a secondary source.

    Pass `None` to disable. Caller owns the lifecycle (open the search
    session in a `with` block and call this from inside).
    """
    global _PLAYPHRASE
    _PLAYPHRASE = pp


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


def _scan_local_cache(text: str, cache_dir: Path, excluded: set[str]) -> list[Chunk]:
    """Scan every cached transcript for clips that already contain the phrase.

    A clip we downloaded for a different chunk often contains shorter target
    phrases for free. This expands our effective candidate pool by 5-10x and,
    crucially, gives us fresh clips to use across variants without ever
    hitting yarn's hard 20-result ceiling.
    """
    if not cache_dir.exists():
        return []
    out: list[Chunk] = []
    for words_file in cache_dir.glob("*.words.json"):
        clip_id = words_file.name.replace(".words.json", "")
        if clip_id in excluded:
            continue
        mp4 = cache_dir / f"{clip_id}.mp4"
        if not mp4.exists():
            continue
        try:
            words = json.loads(words_file.read_text(encoding="utf-8"))
        except Exception:
            continue
        match = find_phrase(words, text)
        if match is None or match.score < 1.0:
            continue
        out.append(Chunk(text=text, clip_id=clip_id, mp4=mp4, start=match.start, end=match.end))
    return out


def _try_chunk(
    chunk_words: list[str],
    yarn: YarnSearch,
    cache_dir: Path,
    max_candidates: int = 20,
) -> Chunk | None:
    """Is there a clip where this subsequence is spoken in order?

    Order of attempts:
        1. Local transcript cache, fresh (non-excluded) clips only
        2. Negative cache check (skip phrases known to fail everywhere)
        3. Yarn fresh search + download + transcribe
        4. Last resort: reuse an already-used local clip rather than skipping
           the word. Variant uniqueness is a soft preference; full word
           coverage is a hard requirement.

    If env var BUMBLEBEE_SHUFFLE=1 is set, candidates are shuffled, giving
    different variants different cuts of the same phrase.
    """
    text = " ".join(chunk_words)
    excluded = _excluded_ids()
    shuffle = os.environ.get("BUMBLEBEE_SHUFFLE") == "1"

    # Scan everything once; the result is reused for both the fresh path and
    # the reuse-fallback path.
    all_local_hits = _scan_local_cache(text, cache_dir, set())
    fresh_hits = [h for h in all_local_hits if h.clip_id not in excluded]

    # 1. Fresh local cache — best case, instant
    if fresh_hits:
        if shuffle:
            random.shuffle(fresh_hits)
        chunk = fresh_hits[0]
        print(f"        . cache hit for {text!r} -> {chunk.clip_id[:8]} "
              f"({len(fresh_hits)} fresh options in local cache)")
        return chunk

    # 2. Negative cache — only honoured for phrases we've never matched.
    # If a phrase exists in local cache (even fully excluded) we can still
    # reuse it later, so it must never be poisoned.
    if not all_local_hits and text in _NEGATIVE_CACHE:
        print(f"        . cached miss for {text!r} (skipping yarn)")
        return None

    # 3. Yarn search for new candidates
    clip_ids = yarn.search(text, max_results=max_candidates)
    if not clip_ids:
        print(f"        . yarn: 0 ids for {text!r}")
        if not all_local_hits:
            _NEGATIVE_CACHE.add(text)
        # Fall through to step 4 — maybe we can reuse an excluded local clip.
    else:
        if shuffle:
            random.shuffle(clip_ids)
        # Prefer ids we haven't used yet, but keep the original list as a
        # backstop in case all yarn results overlap with our excluded set.
        original_ids = list(clip_ids)
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

    # 4. Optional playphrase fallback. Triggered only when yarn produced no
    # match — playphrase has a much larger pool especially for rare words,
    # and its API delivers word-timestamps natively so we skip transcription.
    if _PLAYPHRASE is not None:
        try:
            pp_clips = _PLAYPHRASE.search(text, max_results=5)
        except Exception as e:
            print(f"        ! playphrase search failed for {text!r}: {e}")
            pp_clips = []
        if pp_clips:
            print(f"        . playphrase: {len(pp_clips)} clips for {text!r}")
        for c in pp_clips:
            if c.clip_id in excluded:
                continue
            from .playphrase_search import cache_clip as pp_cache
            path = pp_cache(c, cache_dir)
            if path is None:
                continue
            match = find_phrase(c.words, text)
            if match is None or match.score < 1.0:
                continue
            return Chunk(
                text=text, clip_id=c.clip_id, mp4=path,
                start=match.start, end=match.end,
            )

    # 5. Last resort — reuse an already-used local-cache clip, but only for
    # single-word chunks. Reusing a multi-word chunk would make greedy stop
    # exploring shorter splits that may still have fresh candidates, which
    # collapses variant diversity for the entire tail of the phrase. For a
    # single word that's genuinely exhausted (e.g. a rare proper noun), reuse
    # is still better than dropping the word.
    if all_local_hits and len(chunk_words) == 1:
        if shuffle:
            random.shuffle(all_local_hits)
        chunk = all_local_hits[0]
        print(f"        . reusing excluded clip for {text!r} -> "
              f"{chunk.clip_id[:8]} (single-word fresh pool exhausted)")
        return chunk

    # Truly nothing matched anywhere — let the caller try shorter chunks
    # (or skip the word if this is already a single token).
    _NEGATIVE_CACHE.add(text)
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
