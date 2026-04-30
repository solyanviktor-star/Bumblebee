"""Bumblebee CLI — assemble a long phrase from real movie clips.

Usage:
    python bumblebee.py "I am your father"
    python bumblebee.py "I am your father" "Houston we have a problem"
    python bumblebee.py -o myvideo.mp4 "any phrase"
    python bumblebee.py "Sentient is the best" --variants 5

Each positional argument is treated as an independent phrase. All resulting
clips are concatenated in order into output/<name>.mp4.

Pipeline:
  greedy splitter: cut into the largest chunks (<=6 words) that exist in cinema
  -> for each chunk: yarn -> download -> Whisper word-timestamps -> exact match -> cut
  -> concat all parts -> output/final.mp4
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

# Windows cp1251 -> UTF-8 + line-buffered (so progress shows up immediately)
try:
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
    sys.stderr.reconfigure(encoding="utf-8", line_buffering=True)
except Exception:
    pass

# Global flush for every print
import builtins as _builtins
_orig_print = _builtins.print
def _flushed_print(*args, **kw):
    kw.setdefault("flush", True)
    _orig_print(*args, **kw)
_builtins.print = _flushed_print

from src.concat import concat
from src.cutter import cut
from src.phrase_splitter import Chunk, add_excluded, greedy_split, reset_excluded
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
        print(f"      + {c.text!r}  <-  {c.clip_id[:8]}  [{c.start:.2f}-{c.end:.2f}s]")
    elif stage == "skip":
        print(f"      - {kw['word']!r} not found in any clip, skipping")


_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")


def split_into_sentences(text: str) -> list[str]:
    """Split text into sentences by . ! ?. Empty parts are dropped."""
    parts = [p.strip() for p in _SENTENCE_RE.split(text)]
    return [p for p in parts if p]


def process_phrase(phrase: str, idx: int, yarn: YarnSearch) -> tuple[list[Path], list[str]]:
    """Return (list of cut part-files, list of full clip_ids used)."""
    print(f"\n[{idx}] {phrase!r}")

    sentences = split_into_sentences(phrase)
    print(f"    sentences: {len(sentences)}")

    parts: list[Path] = []
    used: list[str] = []
    sub = 0
    for sn, sentence in enumerate(sentences, start=1):
        print(f"    [{idx}.{sn}] {sentence!r}")
        chunks, skipped = greedy_split(sentence, yarn, CACHE, on_step=_on_step)
        if not chunks:
            print(f"      nothing matched")
            continue
        print(f"      assembled: {len(chunks)} chunks, skipped words: {len(skipped)}")
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
    parser = argparse.ArgumentParser(description="Bumblebee — surgical phrase splicing from movies")
    parser.add_argument("phrases", nargs="+", help="Phrases in English")
    parser.add_argument("-o", "--output", default="final.mp4", help="Output filename inside output/")
    parser.add_argument("--variants", type=int, default=1,
                        help="How many distinct variants to generate. >1 enables mix mode: every "
                             "variant avoids clips used by previous ones. Files are named "
                             "<output>_v1.mp4, _v2.mp4, ...")
    args = parser.parse_args()

    if args.variants > 1:
        os.environ["BUMBLEBEE_SHUFFLE"] = "1"

    final_paths: list[Path] = []
    with YarnSearch() as yarn:
        for v in range(1, args.variants + 1):
            if args.variants > 1:
                print(f"\n========== variant {v}/{args.variants} ==========")
            all_parts: list[Path] = []
            used_full_ids: list[str] = []
            for i, phrase in enumerate(args.phrases, start=1):
                parts, used = process_phrase(phrase, i, yarn)
                all_parts.extend(parts)
                used_full_ids.extend(used)
            if not all_parts:
                print(f"\n[variant {v}] no chunks assembled", file=sys.stderr)
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
            print(f"\n+ [{v}] {final}  ({len(all_parts)} chunks)")
            if args.variants > 1:
                add_excluded(used_full_ids)

    return 0 if final_paths else 1


if __name__ == "__main__":
    sys.exit(main())
