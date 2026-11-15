import math
import os
import re
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


def parse_price(value) -> float:
    try:
        return float(re.sub(r"[^0-9.]", "", str(value)))
    except (TypeError, ValueError):
        return 0.0


def discount_percent(product: dict) -> float:
    """Discount in percent: the API's "discount" field ("35%"), or computed
    from target_original_price vs target_sale_price."""
    raw = product.get("discount")
    if raw not in (None, ""):
        pct = parse_price(raw)
        if 0 < pct < 100:
            return pct
    original = parse_price(product.get("target_original_price"))
    sale = parse_price(product.get("target_sale_price"))
    if original > 0 and 0 < sale < original:
        return round((1 - sale / original) * 100, 1)
    return 0.0


def rank_products(products: list[dict], min_rating: float | None = None) -> list[dict]:
    """Order annotated products (see annotate_product) best first.

    1. Relevance to the query, in buckets of 25 points, so a title that
       matches all search words beats one that matches half of them.
    2. Within a bucket, a value score combining rating (40%), sales volume
       (45%, log scale vs. the best seller in the list) and discount (15%).
    Products rated below min_rating (default ALI_MIN_RATING or 85%) are
    dropped, as long as at least 5 products remain."""
    if min_rating is None:
        try:
            min_rating = float(os.getenv("ALI_MIN_RATING", "85"))
        except ValueError:
            min_rating = 85.0

    well_rated = [p for p in products if not p.get("__rate") or p["__rate"] >= min_rating]
    if len(well_rated) >= 5:
        products = well_rated

    max_sales = max((p.get("__total_sales", 0) for p in products), default=0)
    for p in products:
        rate = p.get("__rate") or 0.0
        rate_n = min(1.0, max(0.0, (rate - 80) / 20)) if rate else 0.3  # unknown rating: below average
        sales = p.get("__total_sales", 0)
        sales_n = math.log1p(sales) / math.log1p(max_sales) if max_sales > 0 else 0.0
        p["__discount"] = discount_percent(p)
        disc_n = min(p["__discount"], 80.0) / 80.0
        p["__value_score"] = round(0.40 * rate_n + 0.45 * sales_n + 0.15 * disc_n, 4)

    return sorted(
        products,
        key=lambda x: (-(x.get("__relevance", 0.0) // 25), -x["__value_score"]),
    )


async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print(f"❌ שגיאה: {context.error}")
