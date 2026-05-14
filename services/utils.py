import re
import pyshorteners
from telegram.ext import ContextTypes
from telegram import Update

FOOTWEAR_QUERY_TERMS = {
    "shoe", "shoes", "sneaker", "sneakers", "boot", "boots",
    "sandal", "sandals", "slipper", "slippers", "footwear",
}

FOOTWEAR_ACCESSORY_TERMS = {
    "repair", "patch", "patches", "sticker", "stickers", "insole", "insoles",
    "heel", "protector", "protectors", "guard", "guards", "holder", "kit",
    "kits", "spike", "spikes", "nail", "nails", "accessory", "accessories",
    "tool", "tools", "replacement", "parts", "set", "adhesive", "glue",
}

FOOTWEAR_PRODUCT_TERMS = {
    "shoe", "shoes", "sneaker", "sneakers", "boot", "boots",
    "sandal", "sandals", "slipper", "slippers", "loafer", "loafers",
    "running", "walking",
}


def tokenize(text):
    return re.findall(r'\b\w+\b', text.lower())


def is_footwear_query(keyword_words: list[str]) -> bool:
    return any(word in FOOTWEAR_QUERY_TERMS for word in keyword_words)


def search_relevance_score(product_title: str, keyword_words: list[str]) -> float:
    title_words = tokenize(product_title)
    keyword_set = set(keyword_words)

    if not keyword_set:
        return 0.0

    match_count = sum(1 for word in keyword_set if word in title_words)
    base_ratio = match_count / max(1, len(keyword_set))
    score = base_ratio * 100

    if is_footwear_query(keyword_words):
        product_hits = sum(1 for word in title_words if word in FOOTWEAR_PRODUCT_TERMS)
        accessory_hits = sum(1 for word in title_words if word in FOOTWEAR_ACCESSORY_TERMS)
        score += product_hits * 6
        score -= accessory_hits * 25

    return score


def match_search_words(product_title: str, keyword_words: list[str], threshold: float = 0.5) -> bool:
    title_words = tokenize(product_title)
    match_count = sum(1 for word in keyword_words if word in title_words)
    ratio_ok = (match_count / max(1, len(keyword_words))) >= threshold
    if not ratio_ok:
        return False

    if is_footwear_query(keyword_words):
        product_hits = sum(1 for word in title_words if word in FOOTWEAR_PRODUCT_TERMS)
        accessory_hits = sum(1 for word in title_words if word in FOOTWEAR_ACCESSORY_TERMS)
        if accessory_hits > 0 and product_hits <= 1:
            return False

    return True


def shorten_url(long_url):
    try:
        return pyshorteners.Shortener().tinyurl.short(long_url)
    except Exception as e:
        print(f"URL shortening error: {e}")
        return long_url


async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print(f"❌ שגיאה: {context.error}")
