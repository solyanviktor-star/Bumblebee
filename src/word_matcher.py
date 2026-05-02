"""Find the exact time bounds of a phrase inside a word-level transcript.

Algorithm:
1. Tokenize the target phrase (lowercase, punctuation stripped).
2. Look for a contiguous subsequence of matching words in the transcript.
3. If no exact run is found, fall back to the longest partial run.
4. Return (start_of_first_word - pad, end_of_last_word + pad).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_TOKEN_RE = re.compile(r"[a-z0-9']+")
_PAD_BEFORE = 0.015  # 15 ms — minimum, so the attack of the sound isn't clipped
_PAD_AFTER = 0.030   # 30 ms — short tail so the trailing phoneme stays intact

# Whisper sometimes returns a word with `end == start` (or near-zero duration)
# when its forced alignment can't pin the boundaries — usually because the
# word is mumbled, swallowed by the next word, or the audio doesn't actually
# contain it (small.en hallucinates short tokens like 'thank', 'a', 'the').
# Cuts driven by such timestamps produce silence or the wrong syllable, so
# we treat those matches as invalid.
_MIN_WORD_DURATION = 0.04  # seconds — anything shorter is almost certainly misalignment


def _has_plausible_durations(words: list[dict], start_idx: int, length: int) -> bool:
    """True if every matched word has a non-degenerate duration."""
    for j in range(length):
        w = words[start_idx + j]
        if (w["end"] - w["start"]) < _MIN_WORD_DURATION:
            return False
    return True


@dataclass
class Match:
    start: float
    end: float
    matched_words: int
    total_words: int

    @property
    def score(self) -> float:
        return self.matched_words / self.total_words if self.total_words else 0.0


def tokenize(phrase: str) -> list[str]:
    return _TOKEN_RE.findall(phrase.lower())


def _word_eq(target_w: str, transcript_w: str) -> bool:
    """Words count as a match if any of these hold:
       - exact equality
       - the transcript word starts with the target ('get' in 'getting', 'I' in "I'm")
       - same after stripping apostrophes from both ('didnt' <-> "didn't", 'were' <-> "we're")
    This is a precision tradeoff — we cut a whole transcript word, not a substring,
    but without it long colloquial phrases never match.
    """
    if target_w == transcript_w:
        return True
    if transcript_w.startswith(target_w):
        return True
    t_clean = transcript_w.replace("'", "")
    g_clean = target_w.replace("'", "")
    if t_clean == g_clean:
        return True
    if t_clean.startswith(g_clean):
        return True
    return False


def find_phrase(words: list[dict], phrase: str) -> Match | None:
    """Locate the phrase in word-timestamps. Returns None if not a single word matches."""
    target = tokenize(phrase)
    if not target or not words:
        return None

    transcript = [w["word"] for w in words]
    n_t = len(target)

    # 1. Exact (with apostrophe / prefix fuzz) match of the full target in order
    for i in range(len(transcript) - n_t + 1):
        if all(_word_eq(target[j], transcript[i + j]) for j in range(n_t)):
            if not _has_plausible_durations(words, i, n_t):
                continue
            return Match(
                start=max(0.0, words[i]["start"] - _PAD_BEFORE),
                end=words[i + n_t - 1]["end"] + _PAD_AFTER,
                matched_words=n_t,
                total_words=n_t,
            )

    # 2. Best partial — the longest contiguous matched run we can find
    best: tuple[int, int, int] | None = None
    for i in range(len(transcript)):
        for j in range(n_t):
            k = 0
            while (i + k < len(transcript)
                   and j + k < n_t
                   and _word_eq(target[j + k], transcript[i + k])):
                k += 1
            if k > 0 and _has_plausible_durations(words, i, k):
                if best is None or k > best[0]:
                    best = (k, i, i + k - 1)

    if best is None:
        return None

    length, s_idx, e_idx = best
    return Match(
        start=max(0.0, words[s_idx]["start"] - _PAD_BEFORE),
        end=words[e_idx]["end"] + _PAD_AFTER,
        matched_words=length,
        total_words=n_t,
    )
