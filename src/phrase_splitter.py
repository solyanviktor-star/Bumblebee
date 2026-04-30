"""Greedy longest-match splitter.

Алгоритм:
  i = 0
  while i < len(words):
      for chunk_len in range(min(MAX_CHUNK, n - i), 0, -1):
          chunk = words[i : i + chunk_len]
          если найден клип, где эта подпоследовательность звучит подряд → берём
              i += chunk_len
              break
      else:
          # одно слово не нашлось — пропускаем
          i += 1

«Найден клип» = yarn.co отдал кандидатов, мы скачали + транскрибировали + word_matcher
вернул score == 1.0 (все слова куска подряд).
"""
from __future__ import annotations

import os
import random
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

from .downloader import download_clip
from .transcriber import transcribe_words
from .word_matcher import find_phrase
from .yarn_search import YarnSearch

_TOKEN_RE = re.compile(r"[A-Za-z0-9']+")

# Глобальный set исключённых clip_id — для генерации непересекающихся вариантов.
# Заполняется снаружи через add_excluded() / reset_excluded().
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
    """Скачать + транскрибировать + матчить один клип. None если не подходит.
    Любая ошибка логируется, чтобы не было silent skip."""
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
    """Есть ли клип, где эта подпоследовательность звучит подряд?
    Серийно перебираем кандидатов — на первом exact-match выходим.
    (Параллелизм через Groq client не thread-safe — оборачивался silent-фейлом.)

    Если переменная BAMBLBE_SHUFFLE=1 — перемешиваем кандидатов случайно (для
    генерации разнообразных вариантов нарезки на одной и той же фразе).
    """
    text = " ".join(chunk_words)
    clip_ids = yarn.search(text, max_results=max_candidates)
    if not clip_ids:
        print(f"        · yarn: 0 ids for {text!r}")
        return None
    if os.environ.get("BAMBLBE_SHUFFLE") == "1":
        random.shuffle(clip_ids)
    # Пропускаем clip_id, уже использованные в предыдущих вариантах (mix-mode).
    # Если все исключены — fallback: пробуем как обычно.
    excluded = _excluded_ids()
    if excluded:
        filtered = [c for c in clip_ids if c not in excluded]
        if filtered:
            clip_ids = filtered
    print(f"        · yarn: {len(clip_ids)} ids for {text!r}")

    for clip_id in clip_ids:
        result = _check_candidate(clip_id, text, cache_dir)
        if result is None:
            # узнаем что транскрипт показал — для диагностики
            try:
                from .transcriber import transcribe_words
                from .downloader import download_clip
                mp4 = download_clip(clip_id, cache_dir)
                words = transcribe_words(mp4)
                t = " ".join(w["word"] for w in words)
                print(f"        · {clip_id[:8]} no-match. transcript: {t!r}")
            except Exception as e:
                print(f"        · {clip_id[:8]} debug-log fail: {e}")
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
    """Вернуть (найденные куски в порядке, пропущенные слова).

    on_step(stage, **kwargs) — callback для прогресса (опц.)
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
