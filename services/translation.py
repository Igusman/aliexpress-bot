import os
from typing import Dict, Tuple

import requests
from deep_translator import GoogleTranslator
from dotenv import load_dotenv

load_dotenv()

PROVIDER_ORDER = ["google", "chatgpt"]
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
    return GoogleTranslator(source=source_code, target=target).translate(text)


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
    if provider == "chatgpt":
        return _translate_chatgpt(text, source, target)
    raise ValueError(f"Unsupported provider: {provider}")


async def compare_translations(text: str, source: str = "he", target: str = "en") -> Dict[str, Dict[str, str]]:
    results: Dict[str, Dict[str, str]] = {}
    for provider in PROVIDER_ORDER:
        try:
            translated = _normalize_text(_translate_with_provider(provider, text, source, target))
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


def _pick_provider(comparison: Dict[str, Dict[str, str]]) -> Tuple[str, str]:
    preferred = os.getenv("TRANSLATION_PROVIDER", PREFERRED_PROVIDER).strip().lower()
    ordered = [preferred] + [p for p in PROVIDER_ORDER if p != preferred]

    for provider in ordered:
        info = comparison.get(provider, {})
        translated = _normalize_text(info.get("translated_text", ""))
        if info.get("status") == "ok" and translated:
            return translated, provider

    return "", "none"


async def translate_to_english_with_debug(text: str) -> Tuple[str, str, Dict[str, Dict[str, str]]]:
    comparison = await compare_translations(text, source="he", target="en")
    selected_text, provider = _pick_provider(comparison)
    if not selected_text:
        selected_text = text
    return selected_text, provider, comparison


async def translate_to_english(text: str):
    try:
        translated_text, _, _ = await translate_to_english_with_debug(text)
        return translated_text
    except Exception as e:
        print(f"Translation error (to English): {e}")
        return text

async def translate_to_hebrew(text: str):
    try:
        comparison = await compare_translations(text, source="en", target="he")
        translated_text, _ = _pick_provider(comparison)
        return translated_text or text
    except Exception as e:
        print(f"Translation error (to Hebrew): {e}")
        return text
