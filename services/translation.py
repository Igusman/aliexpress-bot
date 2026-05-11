import os
from deep_translator import GoogleTranslator
from dotenv import load_dotenv

load_dotenv()

def is_hebrew(text: str) -> bool:
    return any('\u0590' <= c <= '\u05EA' for c in text)

async def translate_to_english(text: str):
    try:
        translator = GoogleTranslator(source_language='he', target_language='en')
        return translator.translate(text)
    except Exception as e:
        print(f"Translation error (to English): {e}")
        return text

async def translate_to_hebrew(text: str):
    try:
        translator = GoogleTranslator(source_language='auto', target_language='he')
        return translator.translate(text)
    except Exception as e:
        print(f"Translation error (to Hebrew): {e}")
        return text
