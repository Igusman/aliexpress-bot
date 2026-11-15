import asyncio
import os
import time
from typing import Dict, Tuple

import requests
from deep_translator import GoogleTranslator, MyMemoryTranslator
from dotenv import load_dotenv

load_dotenv()

# Free providers first; ChatGPT (paid) is the last resort.
PROVIDER_ORDER = ["google", "mymemory", "chatgpt"]
PREFERRED_PROVIDER = "google"


def _normalize_text(value: str) -> str:
    return (value or "").strip()

def is_hebrew(text: str) -> bool:
    return any('\u0590' <= c <= '\u05EA' for c in text)


# Google Translate uses 'iw' for Hebrew (legacy ISO code), not 'he'
_GOOGLE_LANG_MAP = {
    "he": "iw",
    "en": "en",
    "auto": "auto",
}


def _translate_google(text: str, source: str, target: str) -> str:
    source_code = _GOOGLE_LANG_MAP.get(source, source)
    target_code = _GOOGLE_LANG_MAP.get(target, target)
    return GoogleTranslator(source=source_code, target=target_code).translate(text)


_MYMEMORY_LANG_MAP = {"he": "hebrew", "en": "english"}


def _translate_mymemory(text: str, source: str, target: str) -> str:
    # Free MyMemory API (no key, ~5000 chars/day per IP), used when Google is rate-limited.
    return MyMemoryTranslator(
        source=_MYMEMORY_LANG_MAP.get(source, source),
        target=_MYMEMORY_LANG_MAP.get(target, target),
    ).translate(text)


def _translate_chatgpt(text: str, source: str, target: str) -> str:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY is not set")

    model = os.getenv("OPENAI_MODEL", "gpt-4o")
    lang_name = {"he": "Hebrew", "en": "English", "auto": "detected language"}
    source_name = lang_name.get(source, source)
    target_name = lang_name.get(target, target)

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "temperature": 0,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a translation engine. Return only the translated text without quotes or explanations."
                ),
            },
            {
                "role": "user",
                "content": f"Translate from {source_name} to {target_name}: {text}",
            },
        ],
    }

    response = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers=headers,
        json=payload,
        timeout=20,
    )
    response.raise_for_status()
    data = response.json()
    translated = data["choices"][0]["message"]["content"]
    return _normalize_text(translated)


def _translate_with_provider(provider: str, text: str, source: str, target: str) -> str:
    if provider == "google":
        return _translate_google(text, source, target)
    if provider == "mymemory":
        return _translate_mymemory(text, source, target)
    if provider == "chatgpt":
        return _translate_chatgpt(text, source, target)
    raise ValueError(f"Unsupported provider: {provider}")


def _provider_order() -> list:
    preferred = os.getenv("TRANSLATION_PROVIDER", PREFERRED_PROVIDER).strip().lower()
    return [preferred] + [p for p in PROVIDER_ORDER if p != preferred]


def _compare_debug_enabled() -> bool:
    return os.getenv("TRANSLATION_COMPARE_DEBUG", "0").strip().lower() in {"1", "true", "yes", "on"}


# A provider that answered "too many requests" is skipped for this long.
RATE_LIMIT_COOLDOWN_SECONDS = 120
_cooldown_until: Dict[str, float] = {}

# Small in-memory cache: the same queries and product titles come up often.
_CACHE_MAX = 2000
_cache: Dict[Tuple[str, str, str], Tuple[str, str]] = {}


def _is_rate_limit_error(error: Exception) -> bool:
    text = str(error).lower()
    return "too many requests" in text or "429" in text or "quota" in text


async def translate(text: str, source: str, target: str) -> Tuple[str, str]:
    """Translate with the preferred provider, falling back to the next one
    only if it fails or returns an empty string. Providers that are
    rate-limited are skipped for RATE_LIMIT_COOLDOWN_SECONDS.
    Returns (translated_text, provider); ("", "none") if all providers fail."""
    text = _normalize_text(text)
    if not text:
        return "", "none"
    key = (text, source, target)
    if key in _cache:
        return _cache[key]

    for provider in _provider_order():
        if _cooldown_until.get(provider, 0) > time.monotonic():
            continue
        try:
            translated = _normalize_text(
                await asyncio.to_thread(_translate_with_provider, provider, text, source, target)
            )
        except Exception as e:
            print(f"Translation error ({provider}, {source}->{target}): {e}")
            if _is_rate_limit_error(e):
                _cooldown_until[provider] = time.monotonic() + RATE_LIMIT_COOLDOWN_SECONDS
                print(f"Translation provider {provider} rate-limited, skipping it for {RATE_LIMIT_COOLDOWN_SECONDS}s")
            continue
        if translated:
            if len(_cache) >= _CACHE_MAX:
                _cache.pop(next(iter(_cache)))
            _cache[key] = (translated, provider)
            return translated, provider
    return "", "none"


async def compare_translations(text: str, source: str = "he", target: str = "en") -> Dict[str, Dict[str, str]]:
    """Run every provider on the same text. Debug only (TRANSLATION_COMPARE_DEBUG=1)."""
    results: Dict[str, Dict[str, str]] = {}
    for provider in PROVIDER_ORDER:
        try:
            translated = _normalize_text(
                await asyncio.to_thread(_translate_with_provider, provider, text, source, target)
            )
            results[provider] = {
                "translated_text": translated,
                "status": "ok",
            }
        except Exception as e:
            results[provider] = {
                "translated_text": text,
                "status": "error",
                "error": str(e),
            }
    return results


async def translate_to_english_with_debug(text: str) -> Tuple[str, str, Dict[str, Dict[str, str]]]:
    comparison: Dict[str, Dict[str, str]] = {}
    if _compare_debug_enabled():
        comparison = await compare_translations(text, source="he", target="en")
    selected_text, provider = await translate(text, source="he", target="en")
    if not selected_text:
        selected_text = text
    return selected_text, provider, comparison


async def translate_to_english(text: str):
    try:
        translated_text, _ = await translate(text, source="he", target="en")
        return translated_text or text
    except Exception as e:
        print(f"Translation error (to English): {e}")
        return text


async def translate_to_hebrew(text: str):
    try:
        translated_text, _ = await translate(text, source="en", target="he")
        return translated_text or text
    except Exception as e:
        print(f"Translation error (to Hebrew): {e}")
        return text


async def translate_titles_to_hebrew(titles: list[str]) -> list[str]:
    """Translate several titles with a single request (one per line) instead
    of one request per title, which quickly hits Google's rate limit.
    Falls back to one-by-one if the line count doesn't come back intact.
    Untranslatable titles are returned unchanged."""
    clean = [" ".join((t or "").split()) for t in titles]
    if not clean:
        return []
    joined, _ = await translate("\n".join(clean), source="en", target="he")
    lines = [line.strip() for line in joined.split("\n") if line.strip()] if joined else []
    if len(lines) == len(clean):
        return lines
    results = []
    for title in clean:
        translated, _ = await translate(title, source="en", target="he")
        results.append(translated or title)
    return results
