# Bumblebee

[![Available on skills.sh](https://img.shields.io/badge/skills.sh-Bumblebee-black?style=flat-square)](https://skills.sh)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg?style=flat-square)](LICENSE)
[![Python 3.9+](https://img.shields.io/badge/Python-3.9%2B-blue.svg?style=flat-square)](https://www.python.org/)

Surgical phrase splicing from real movies and TV shows via [yarn.co](https://yarn.co).

Give it any long phrase — it greedily cuts the line into the longest possible runs of words that were actually spoken on screen, then assembles a final clip from those pieces. Classic fragmovie genre, automated to the millisecond.

100% local, no API keys, no cloud calls. Speech recognition runs on-device with [faster-whisper](https://github.com/SYSTRAN/faster-whisper).

## Install as an Agent Skill

```bash
npx skills add solyanviktor-star/Bumblebee
```

This installs Bumblebee into your agent's skills directory ([Claude Code](https://claude.ai/code), [Cursor](https://cursor.com), [GitHub Copilot](https://github.com/), and [other compatible agents](https://agentskills.io)). The agent will automatically activate it on prompts like *"splice a fragmovie of \<phrase\>"* or *"build a video where actors say \<phrase\>"*.

## How it works

```
"I don't get it, why does my Claude keep getting banned. I'm sick of buying new accounts."
        |
        v   split on .!? -> each sentence handled independently
        |
[ greedy splitter — chunks of up to 6 words ]
        |
   "I don't get it why"          --+
   "does"                        --+   for each chunk:
   "Claude"                      --+     getyarn.io -> 8 candidates  (curl_cffi, bypasses CF)
   "keep getting"                --+     download mp4
   "I'm sick of"                 --+     faster-whisper word-timestamps (local, no API)
   "new accounts"                --+     word_matcher: exact match
   ...                              |    FFmpeg cut to the millisecond
                                    v
                          concat into output/final.mp4
                          (with short audio fades at every splice +
                          a ~180ms breathing pause between sentences)
```

Words that nobody ever said in any clip are skipped.

## Mix mode: multiple takes on one phrase

```bash
python bumblebee.py "Sentient is the best company" --variants 4 -o sentient.mp4
```

Generates 4 files (`sentient_v1.mp4`, `_v2`, `_v3`, `_v4`) where **every variant avoids clips already used by previous ones**. You get different cuts with different actors, different movies, sometimes even different segmentation of the same phrase.

## Install

```bash
git clone https://github.com/solyanviktor-star/Bumblebee.git
cd Bumblebee
pip install -r requirements.txt
```

You also need **FFmpeg** on PATH (or set `FFMPEG_BIN` to its path).

That's it. No API keys, no `.env`, nothing else to configure. The first run downloads the Whisper model (~244 MB for `small.en`) into the HuggingFace cache; every run after that is fully offline.

## Requirements

- Python 3.9+
- FFmpeg
- ~250 MB free disk space for the speech model

No GPU required. If you have a CUDA GPU, set `WHISPER_DEVICE=cuda` for a roughly 5x speedup on transcription.

## Usage

```bash
# One video from one phrase
python bumblebee.py "I am your father"

# Several phrases — each is processed and they're concatenated in order
python bumblebee.py "I am your father" "Houston we have a problem"

# 5 different cuts of the same phrase, no clip reuse
python bumblebee.py "Sentient is the best" -o sentient.mp4 --variants 5
```

The final file lands in `output/<name>.mp4`.

## Optional environment variables

| Variable | Default | Purpose |
|---|---|---|
| `WHISPER_MODEL` | `small.en` | Model name. Use `base.en` for speed, `medium.en` for accuracy. |
| `WHISPER_DEVICE` | `cpu` | Set to `cuda` if you have an NVIDIA GPU. |
| `WHISPER_COMPUTE_TYPE` | `int8` (cpu) / `float16` (cuda) | Inference quantization. |
| `FFMPEG_BIN` | `ffmpeg` | Path to ffmpeg binary if not on PATH. |

## Project layout

```
Bumblebee/
|- bumblebee.py             <- CLI entry point
|- SKILL.md                 <- Claude Code skill manifest
|- src/
|  |- phrase_splitter.py    <- greedy longest-match with optional shuffling/exclusion
|  |- yarn_search.py        <- phrase -> clip_ids (curl_cffi, bypasses Cloudflare)
|  |- downloader.py         <- clip_id -> local mp4 (curl_cffi, bypasses CF on y.yarn.co)
|  |- transcriber.py        <- faster-whisper word-timestamps + cache
|  |- word_matcher.py       <- exact start/end of target words with apostrophe-fuzz
|  |- cutter.py             <- FFmpeg cut + audio fade at splice points
|  |- concat.py             <- concat demuxer
|- cache/                   <- downloaded clips and transcripts (reused across runs)
|- output/                  <- final reels and intermediate parts in _parts/
```

## Known limitations

- yarn.co indexes English-language media only.
- Whisper sometimes transcribes short tokens like "I", "a", "my" as part of a longer word, so single short words tend to get skipped.
- Word order is strict: "can we" and "we can" are different matches (a swap-fuzzy is on the TODO list).
- yarn.co sits behind Cloudflare. Solved with `curl_cffi` and `impersonate='chrome'` (which replays a real Chrome TLS fingerprint).

## License

MIT — see `LICENSE`.

Built end-to-end with [Claude Code](https://claude.com/claude-code).
