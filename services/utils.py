import re
import pyshorteners
from telegram.ext import ContextTypes
from telegram import Update

def tokenize(text):
    return re.findall(r'\b\w+\b', text.lower())

def match_search_words(product_title: str, keyword_words: list[str]) -> bool:
    title_words = tokenize(product_title)
    match_count = sum(1 for word in keyword_words if word in title_words)
    return match_count / max(1, len(keyword_words)) >= 0.5

def shorten_url(long_url):
    try:
        return pyshorteners.Shortener().tinyurl.short(long_url)
    except:
        return long_url

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print(f"❌ שגיאה: {context.error}")
