"""Bumblebee CLI — собирает длинную фразу из реальных кинофрагментов.

Usage:
    python bumblebee.py "Так я не понял почему мой клод всегда банит"
    python bumblebee.py "I am your father" "Houston we have a problem"
    python bumblebee.py -o myvideo.mp4 "any phrase"

Каждый аргумент — независимая фраза. Все результаты склеиваются по очереди.

Внутри:
  RU? → Groq llama переводит на EN
  → greedy splitter: режем на максимальные куски (≤6 слов), которые есть в кино
  → каждый кусок: yarn → download → Whisper word-timestamps → exact match → cut
  → concat всех кусков → output/final.mp4
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

# Windows cp1251 -> UTF-8 + line-buffered (чтобы прогресс был виден сразу)
try:
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
    sys.stderr.reconfigure(encoding="utf-8", line_buffering=True)
except Exception:
    pass

# Глобальный flush для всех print
import builtins as _builtins
_orig_print = _builtins.print
def _flushed_print(*args, **kw):
    kw.setdefault("flush", True)
    _orig_print(*args, **kw)
_builtins.print = _flushed_print

from dotenv import load_dotenv

from src.concat import concat
from src.cutter import cut
from src.phrase_splitter import Chunk, add_excluded, greedy_split, reset_excluded
from src.translator import has_cyrillic, translate_to_english
from src.yarn_search import YarnSearch

ROOT = Path(__file__).parent
CACHE = ROOT / "cache"
OUTPUT = ROOT / "output"
PARTS = OUTPUT / "_parts"


def _on_step(stage: str, **kw):
    if stage == "try":
        print(f"      ? {kw['text']!r}")
    elif stage == "hit":
        c: Chunk = kw["chunk"]
        print(f"      ✓ {c.text!r}  ←  {c.clip_id[:8]}  [{c.start:.2f}–{c.end:.2f}s]")
    elif stage == "skip":
        print(f"      ✗ {kw['word']!r} — нет в кино, пропускаю")


_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")


def split_into_sentences(text: str) -> list[str]:
    """Разбить текст на предложения по . ! ?. Пустые игнорируем."""
    parts = [p.strip() for p in _SENTENCE_RE.split(text)]
    return [p for p in parts if p]


def process_phrase(phrase_raw: str, idx: int, yarn: YarnSearch) -> tuple[list[Path], list[str]]:
    """Возвращает (список нарезанных part-файлов, список full clip_id использованных)."""
    print(f"\n[{idx}] {phrase_raw!r}")

    if has_cyrillic(phrase_raw):
        phrase_en = translate_to_english(phrase_raw)
        print(f"    RU → EN: {phrase_en!r}")
    else:
        phrase_en = phrase_raw

    sentences = split_into_sentences(phrase_en)
    print(f"    предложений: {len(sentences)}")

    parts: list[Path] = []
    used: list[str] = []
    sub = 0
    for sn, sentence in enumerate(sentences, start=1):
        print(f"    [{idx}.{sn}] {sentence!r}")
        chunks, skipped = greedy_split(sentence, yarn, CACHE, on_step=_on_step)
        if not chunks:
            print(f"      ничего не покрылось")
            continue
        print(f"      собрано: {len(chunks)} кусков, пропущено слов: {len(skipped)}")
        last_idx = len(chunks) - 1
        for k, ch in enumerate(chunks):
            is_end = (k == last_idx) and (sn < len(sentences))
            out_part = PARTS / f"{idx:02d}_{sub:02d}_{ch.clip_id[:8]}.mp4"
            cut(ch.mp4, ch.start, ch.end, out_part, is_sentence_end=is_end)
            parts.append(out_part)
            used.append(ch.clip_id)
            sub += 1
    return parts, used


def main() -> int:
    parser = argparse.ArgumentParser(description="Bumblebee — нарезка длинных фраз из кино")
    parser.add_argument("phrases", nargs="+", help="Фразы (RU или EN)")
    parser.add_argument("-o", "--output", default="final.mp4", help="Имя выходного файла в output/")
    parser.add_argument("--show-browser", action="store_true", help="Не headless (legacy, игнор)")
    parser.add_argument("--variants", type=int, default=1,
                        help="Сколько разных вариантов сделать. >1 включает mix-режим: каждый вариант "
                             "избегает клипов из предыдущих, имена файлов: <output>_v1.mp4, _v2.mp4, ...")
    args = parser.parse_args()

    load_dotenv(ROOT / ".env")

    if args.variants > 1:
        os.environ["BAMBLBE_SHUFFLE"] = "1"

    final_paths: list[Path] = []
    with YarnSearch() as yarn:
        for v in range(1, args.variants + 1):
            if args.variants > 1:
                print(f"\n========== вариант {v}/{args.variants} ==========")
            all_parts: list[Path] = []
            used_full_ids: list[str] = []
            for i, phrase in enumerate(args.phrases, start=1):
                parts, used = process_phrase(phrase, i, yarn)
                all_parts.extend(parts)
                used_full_ids.extend(used)
            if not all_parts:
                print(f"\n[вариант {v}] ни одного куска не собрано", file=sys.stderr)
                continue
            if args.variants > 1:
                stem = Path(args.output).stem
                ext = Path(args.output).suffix or ".mp4"
                name = f"{stem}_v{v}{ext}"
            else:
                name = args.output
            final = OUTPUT / name
            concat(all_parts, final)
            final_paths.append(final)
            print(f"\n✓ [{v}] {final}  ({len(all_parts)} кусков)")
            if args.variants > 1:
                add_excluded(used_full_ids)

    return 0 if final_paths else 1


if __name__ == "__main__":
    sys.exit(main())
