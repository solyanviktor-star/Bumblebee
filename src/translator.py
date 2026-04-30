"""RU → EN перевод через Groq (llama-3.3-70b-versatile)."""
from __future__ import annotations

import os
import re

from groq import Groq

_CYRILLIC = re.compile(r"[А-Яа-яЁё]")
_MODEL = "llama-3.3-70b-versatile"


def has_cyrillic(text: str) -> bool:
    return bool(_CYRILLIC.search(text))


def translate_to_english(text: str, client: Groq | None = None) -> str:
    """Перевести фразу на английский. Английский ввод вернётся как есть."""
    if not has_cyrillic(text):
        return text

    client = client or Groq(api_key=os.environ["GROQ_API_KEY"])
    resp = client.chat.completions.create(
        model=_MODEL,
        temperature=0.3,
        max_tokens=240,
        messages=[
            {
                "role": "system",
                "content": (
                    "You translate Russian into natural spoken English as actually "
                    "said in movies and TV shows.\n"
                    "Rules:\n"
                    "- Use COMMON colloquial CONSTRUCTIONS — replace literal grammar "
                    "with everyday phrasing. Examples of constructions to prefer:\n"
                    "  'я не понял' → 'I don't get it' (not 'I didn't get it')\n"
                    "  'всегда банят' → 'keeps getting banned' (not 'always gets banned')\n"
                    "  'мы можем что-то придумать' → 'can we figure something out'\n"
                    "  'я заебался' → 'I'm sick of this' / 'I'm done with this'\n"
                    "- DO NOT substitute meaningful nouns, names, or specific terms "
                    "with generic ones. Preserve the EXACT subject of the sentence:\n"
                    "  'мой клод' → 'my Claude' (NOT 'my bot' or 'my cloak'). "
                    "Treat unusual loanwords/names as proper nouns and KEEP THEM.\n"
                    "  'аккаунты' → 'accounts' (NOT 'profiles')\n"
                    "- Always use contractions: don't, won't, can't, I'm, we're, it's.\n"
                    "- Keep emotional register (anger, frustration, sarcasm), including "
                    "profanity if present.\n"
                    "- Break run-ons into short natural sentences with punctuation.\n"
                    "- Output ONLY the translated phrase, no quotes, no explanation."
                ),
            },
            {"role": "user", "content": text},
        ],
    )
    return resp.choices[0].message.content.strip().strip('"').strip("'")
