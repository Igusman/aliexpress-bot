import os
from openai import AsyncOpenAI
from dotenv import load_dotenv

load_dotenv()

client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))

def is_hebrew(text: str) -> bool:
    return any('\u0590' <= c <= '\u05EA' for c in text)

async def translate_to_english(text: str):
    try:
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": f"Translate this to English: \"{text}\""}]
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"Translation error (to English): {e}")
        return text

async def translate_to_hebrew(text: str):
    try:
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": f"תרגם לעברית את הטקסט הבא:\n\"{text}\""}]
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"Translation error (to Hebrew): {e}")
        return text
