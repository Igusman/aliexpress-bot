import os
from typing import Dict, Tuple

from deep_translator import (
    DeeplTranslator,
    LibreTranslator,
    MicrosoftTranslator,
    MyMemoryTranslator,
)
from dotenv import load_dotenv

load_dotenv()

PROVIDER_ORDER = ["mymemory", "libre", "deepl", "microsoft"]
PREFERRED_PROVIDER = "mymemory"


def _normalize_text(value: str) -> str:
    return (value or "").strip()

def is_hebrew(text: str) -> bool:
    return any('\u0590' <= c <= '\u05EA' for c in text)


def _translate_mymemory(text: str, source: str, target: str) -> str:
    lang_map = {
        "he": "he-IL",
        "en": "en-US",
    }
    source_code = lang_map.get(source, source)
    target_code = lang_map.get(target, target)
    return MyMemoryTranslator(source=source_code, target=target_code).translate(text)


def _translate_libre(text: str, source: str, target: str) -> str:
    lang_map = {
        "he": "he",
        "en": "en",
        "auto": "auto"
    }
    source_code = lang_map.get(source, source)
    target_code = lang_map.get(target, target)
    
    base_url = os.getenv("LIBRETRANSLATE_URL", "https://libretranslate.de")
    api_key = os.getenv("LIBRETRANSLATE_API_KEY", "")
    
    kwargs = {
        "source": source_code,
        "target": target_code,
        "base_url": base_url,
    }
    if api_key:
        kwargs["api_key"] = api_key
    
    return LibreTranslator(**kwargs).translate(text)


def _translate_deepl(text: str, source: str, target: str) -> str:
    api_key = os.getenv("DEEPL_API_KEY")
    if not api_key:
        raise ValueError("DEEPL_API_KEY is not set")

    source_map = {"he": "HE", "en": "EN", "auto": "auto"}
    target_map = {"he": "HE", "en": "EN-US"}

    return DeeplTranslator(
        api_key=api_key,
        source=source_map.get(source, source.upper()),
        target=target_map.get(target, target.upper()),
    ).translate(text)


def _translate_microsoft(text: str, source: str, target: str) -> str:
    api_key = os.getenv("MICROSOFT_TRANSLATOR_KEY")
    if not api_key:
        raise ValueError("MICROSOFT_TRANSLATOR_KEY is not set")

    region = os.getenv("MICROSOFT_TRANSLATOR_REGION")
    kwargs = {
        "api_key": api_key,
        "source": source,
        "target": target,
    }
    if region:
        kwargs["region"] = region

    return MicrosoftTranslator(**kwargs).translate(text)


def _translate_with_provider(provider: str, text: str, source: str, target: str) -> str:
    if provider == "mymemory":
        return _translate_mymemory(text, source, target)
    if provider == "libre":
        return _translate_libre(text, source, target)
    if provider == "deepl":
        return _translate_deepl(text, source, target)
    if provider == "microsoft":
        return _translate_microsoft(text, source, target)
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
