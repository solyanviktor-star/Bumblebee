"""Найти точные временные границы фразы внутри транскрипта.

Алгоритм:
1. Токенизируем целевую фразу (lower, без знаков препинания).
2. Ищем подпоследовательность подряд идущих слов в транскрипте.
3. Если точного совпадения нет — fallback на лучшее частичное (наибольшее число подряд совпавших).
4. Возвращаем (start_first_word - pad, end_last_word + pad).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_TOKEN_RE = re.compile(r"[a-z0-9']+")
_PAD_BEFORE = 0.015  # 15 ms — минимум, чтобы не отрезать атаку звука
_PAD_AFTER = 0.030   # 30 ms — короткий хвост, чтобы не резать окончание


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
    """Считаем слова совпадающими если:
       - точное совпадение
       - транскрипт начинается с target ('get' ⊂ 'getting', 'I' ⊂ "I'm")
       - то же самое после удаления апострофов с обеих сторон
         ('didnt' ⟷ "didn't", 'were' ⟷ "we're")
    Это компромисс точности — вырезаем целое слово транскрипта, а не подстроку,
    но без него длинные разговорные фразы вообще не матчятся.
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
    """Ищем фразу в word-timestamps. None если в транскрипте нет ни одного слова из фразы."""
    target = tokenize(phrase)
    if not target or not words:
        return None

    transcript = [w["word"] for w in words]
    n_t = len(target)

    # 1. Точное (с fuzzy-апострофом / prefix) вхождение всей цели подряд
    for i in range(len(transcript) - n_t + 1):
        if all(_word_eq(target[j], transcript[i + j]) for j in range(n_t)):
            return Match(
                start=max(0.0, words[i]["start"] - _PAD_BEFORE),
                end=words[i + n_t - 1]["end"] + _PAD_AFTER,
                matched_words=n_t,
                total_words=n_t,
            )

    # 2. Лучший частичный — самая длинная подряд-совпавшая последовательность
    best: tuple[int, int, int] | None = None
    for i in range(len(transcript)):
        for j in range(n_t):
            k = 0
            while (i + k < len(transcript)
                   and j + k < n_t
                   and _word_eq(target[j + k], transcript[i + k])):
                k += 1
            if k > 0 and (best is None or k > best[0]):
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
