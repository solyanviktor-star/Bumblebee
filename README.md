# Bumblebee

Хирургическая нарезка фраз из реальных фильмов и сериалов через [yarn.co](https://yarn.co).

Дай скиллу любую длинную фразу — он жадно режет её на максимальные подпоследовательности слов, которые реально звучали на экране, и собирает финальный ролик из этих кусков. Классический жанр fragmovie, только автоматический и до миллисекунды.

[See English version below.](#bumblebee-en)

---

## Как это работает

```
"Так я не понял, почему мой Claude всегда банит. Я заебался покупать аккаунты."
        ↓ Groq Llama-3.3-70b — разговорный перевод (если RU)
        ↓
"I don't get it, why does my Claude keep getting banned. I'm sick of buying new accounts."
        ↓ split по «.!?» → отдельная обработка каждого предложения
        ↓
[ greedy splitter — режем на куски макс по 6 слов ]
        ↓
   "I don't get it why"          ──┐
   "does"                        ──┤   для каждого куска:
   "Claude"                      ──┤     getyarn.io → 8 кандидатов  (curl_cffi, обход CF)
   "keep getting"                ──┤     download mp4
   "I'm sick of"                 ──┤     Groq Whisper word-timestamps
   "new accounts"                ──┤     word_matcher: точное совпадение
   ...                              │     FFmpeg cut по миллисекундам
                                    ↓
                          concat в output/final.mp4
                          (с короткими audio fades на стыках +
                          паузой ~180ms между предложениями)
```

Слова, которых никто не произнёс ни в одном клипе — пропускаются.

## Mix-режим: несколько вариантов одной фразы

```bash
python bumblebee.py "Sentient is the best company" --variants 4 -o sentient.mp4
```

Сгенерирует 4 файла (`sentient_v1.mp4`, `_v2`, `_v3`, `_v4`), где **каждый вариант избегает клипов из предыдущих**. Получаются разные монтажи с разными актёрами, фильмами, и иногда даже разной структурой нарезки.

## Установка

```bash
git clone https://github.com/<your-user>/bumblebee.git
cd bumblebee
pip install -r requirements.txt
copy .env.example .env  # вписать GROQ_API_KEY
```

Также нужен **FFmpeg** в PATH (или путь в `FFMPEG_BIN` env).

## API ключ

Только один — Groq:
- `GROQ_API_KEY` — для Llama-3.3-70b (перевод) и Whisper-large-v3 (транскрипция)

Получить бесплатно на https://console.groq.com.

## Использование

```bash
# Одно видео из фразы
python bumblebee.py "Любая фраза на русском или английском"

# Несколько фраз, каждая обрабатывается отдельно
python bumblebee.py "I am your father" "Houston we have a problem"

# 5 разных монтажей без повторений клипов
python bumblebee.py "Sentient is the best" -o sentient.mp4 --variants 5
```

Финальный файл попадает в `output/<имя>.mp4`.

## Структура

```
bumblebee/
├── bumblebee.py             ← CLI entry point
├── SKILL.md                 ← Claude Code skill manifest
├── src/
│   ├── translator.py        ← RU → EN через Groq Llama-3.3-70b (киношно-разговорный стиль)
│   ├── phrase_splitter.py   ← greedy longest-match с опциональным shuffling/exclusion
│   ├── yarn_search.py       ← фраза → clip_id (curl_cffi, обход Cloudflare)
│   ├── downloader.py        ← clip_id → локальный mp4 (curl_cffi, обход CF на y.yarn.co)
│   ├── transcriber.py       ← Groq Whisper large-v3 word-timestamps + кэш
│   ├── word_matcher.py      ← точные start/end нужных слов с fuzzy на контракциях
│   ├── cutter.py            ← FFmpeg обрезка + audio fade на стыках
│   └── concat.py            ← concat demuxer
├── cache/                   ← скачанные клипы и транскрипты (переиспользуются)
└── output/                  ← финальные ролики и куски в _parts/
```

## Известные ограничения

- yarn.co только англоязычный → русский вход всегда переводится
- Whisper иногда транскрибирует «I», «my», «a» в составе длинной фразы → одиночные короткие слова чаще всего пропускаются
- Порядок слов строгий: «can we» и «we can» — разные совпадения (swap-fuzzy в TODO)
- yarn.co защищён Cloudflare. Решено через `curl_cffi` с `impersonate='chrome'` (имитирует TLS-fingerprint)

---

# Bumblebee (EN) <a id="bumblebee-en"></a>

Surgical phrase splicing from real movies and TV shows via yarn.co.

Give the script any long phrase — it greedily slices it into the longest possible subsequences of words that were actually spoken on screen, and assembles the final clip out of those pieces. Classic fragmovie genre, automated to the millisecond.

```bash
pip install -r requirements.txt
copy .env.example .env  # add GROQ_API_KEY
python bumblebee.py "Any phrase in English (or Russian)"
python bumblebee.py "Sentient is the best" --variants 5  # 5 unique remixes
```

Needs **FFmpeg** in PATH and a free Groq API key from https://console.groq.com.

Built end-to-end with [Claude Code](https://claude.com/claude-code).
