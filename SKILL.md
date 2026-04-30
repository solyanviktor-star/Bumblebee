---
name: bumblebee
description: Surgical phrase splicing from real movies and TV shows via yarn.co. Takes any English phrase and slices it into the longest possible runs of words actually spoken on screen, then assembles a final reel where every word is delivered by a real actor. Triggers — "splice a line from movies", "make a fragmovie", "build a video from someone else's words", "bumblebee". Runs fully local with faster-whisper — no API keys. Mix mode (--variants N) generates several distinct cuts of one phrase without reusing clips.
---

# Bumblebee Skill

A skill that automatically assembles a fragmovie-style video from an arbitrary phrase.

## When to activate
- The user wants to "splice a phrase out of real movies"
- The user wants a video where other actors speak their text
- Requests like "make a fragmovie", "stitch my line out of cinema", "bumblebee"

## What it does
1. Takes English text (one or more phrases as separate args)
2. Splits each phrase by sentence terminators (.!?), processes sentences independently
3. Greedy longest-match: for each sentence, finds the largest contiguous chunks of words that exist on yarn.co
4. Downloads candidate mp4s, transcribes them locally with faster-whisper (word-level timestamps), checks for exact match
5. Cuts with FFmpeg to millisecond precision, concatenates with short fade-in/out at splices and breathing pauses between sentences
6. Optional: generates N distinct variants without clip reuse via `--variants N`

## Dependencies
- Python 3.9+ with `curl_cffi`, `faster-whisper`
- FFmpeg on PATH (or `FFMPEG_BIN` env var)
- No API keys required

## Run
```bash
python bumblebee.py "I am your father" -o father.mp4
python bumblebee.py "Sentient is the best" -o sentient.mp4 --variants 5
```

## Architecture
- `bumblebee.py` — CLI
- `src/yarn_search.py` — curl_cffi (impersonate=chrome) against getyarn.io, bypasses Cloudflare
- `src/downloader.py` — mp4 download via curl_cffi (yarn.co requires a Chrome TLS fingerprint)
- `src/transcriber.py` — faster-whisper local inference + word-timestamps + JSON cache
- `src/word_matcher.py` — exact match with apostrophe / prefix fuzzing
- `src/phrase_splitter.py` — greedy longest-match, optional shuffling and clip exclusion for variants
- `src/cutter.py` — FFmpeg cut with audio fade at splice points
- `src/concat.py` — concat demuxer

## Known limitations
- yarn.co indexes English-language media only
- Whisper sometimes folds short tokens ("I", "a", "my") into longer words, so isolated short words frequently get skipped — this is an inherent limitation of word-level recognition
- A handful of "popular" yarn clips (e.g. `4e5bfded`) appear in many search results and tend to be picked first; mix mode (`--variants`) is the workaround
- Word order is strict: `can we` does not match `we can` (swap-fuzzy is in the TODO list)
