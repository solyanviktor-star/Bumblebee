---
name: bumblebee
description: Хирургическая нарезка фраз из реальных фильмов и сериалов через yarn.co. Любую длинную фразу режет на максимально длинные подпоследовательности слов, которые звучали в кино, и собирает финальный ролик где каждое слово произнесено реальным актёром. Триггеры — "нарежь фразу из кино", "сделай fragmovie", "собери видео из чужих слов", "bumblebee". Поддерживает русский и английский ввод (RU автоматически переводится Llama). Mix-режим (--variants N) генерирует несколько разных монтажей одной фразы без повторений клипов.
---

# Bumblebee Skill

Скилл для автоматической сборки fragmovie-видео из произвольной фразы.

## Когда активировать
- Пользователь хочет «нарезать фразу из реальных фильмов»
- Нужно собрать видео где чужие актёры произносят его текст
- Запросы вида «сделай fragmovie», «склей мою фразу из кино», «bumblebee»

## Что делает
1. Принимает текст (RU или EN)
2. Если RU — переводит на разговорный английский через Groq Llama-3.3-70b
3. Разбивает по предложениям, в каждом жадно ищет максимальные подпоследовательности слов на yarn.co
4. Скачивает кандидаты (mp4), транскрибирует Groq Whisper word-timestamps, проверяет точное совпадение
5. Вырезает FFmpeg по миллисекундам, склеивает с короткими fade-in/out на стыках, паузами между предложениями
6. Опционально — генерирует N разных вариантов без повторений клипов (`--variants N`)

## Зависимости
- Python 3.11+ с пакетами `curl_cffi`, `groq`, `python-dotenv`
- FFmpeg в PATH или путь в `FFMPEG_BIN`
- `GROQ_API_KEY` в `.env`

## Запуск
```bash
python bumblebee.py "Любая фраза на русском или английском" -o myvideo.mp4
python bumblebee.py "Sentient is the best" -o sentient.mp4 --variants 5
```

## Архитектура
- `bumblebee.py` — CLI
- `src/translator.py` — Groq Llama, RU→EN с разговорным стилем
- `src/yarn_search.py` — curl_cffi (impersonate=chrome) на getyarn.io, обходит Cloudflare
- `src/downloader.py` — скачка mp4 через curl_cffi (yarn.co требует TLS-fingerprint Chrome)
- `src/transcriber.py` — Groq Whisper large-v3 + word-timestamps + кэш
- `src/word_matcher.py` — точный матч с fuzzy на префиксах/контракциях
- `src/phrase_splitter.py` — greedy longest-match, опциональный shuffling и exclusion для variants
- `src/cutter.py` — FFmpeg обрезка с audio fade на стыках
- `src/concat.py` — concat demuxer

## Известные ограничения
- yarn.co только англоязычный → RU вход всегда переводится
- Whisper иногда транскрибирует одно слово как часть длинной фразы → одиночные слова («I», «a», «my») часто пропускаются — это естественное ограничение
- `4e5bfded` и подобные «топовые» клипы могут быть в каждой выдаче yarn — потому в первом варианте они и забираются
- Порядок слов важен: `can we` не матчится `we can` (см. swap-fuzzy todo)
