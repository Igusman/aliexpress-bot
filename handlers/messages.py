import asyncio
import json
import re
import time
import os
from html import escape
from urllib.parse import urlparse
from telegram import Update, InputMediaPhoto
from telegram.ext import ContextTypes
from services.translation import is_hebrew, translate_titles_to_hebrew, translate_to_english_with_debug
from services.aliexpress_api import (
    compare_search_methods,
    enrich_products_with_details,
    fetch_hot_products,
    find_products_in_response,
    generate_affiliate_links,
    product_page_url,
    get_api_error,
    pick_best_count,
    pick_best_rate,
    search_products_with_fallback,
)
from services.logging import log_search
from services.utils import tokenize, match_search_words, rank_products, search_relevance_score

BUTTON_QUERY_MAP = {
    "נעליים": {"keywords": "shoes", "category_env": "ALI_CATEGORY_SHOES"},
    "שעון חכם": {"keywords": "smart watch", "category_env": "ALI_CATEGORY_SMARTWATCH"},
    "אקססוריז טלפון": {"keywords": "phone accessories", "category_env": "ALI_CATEGORY_PHONE_ACCESSORIES"},
}


CURRENCY_SYMBOLS = {"USD": "$", "ILS": "₪", "EUR": "€"}


def format_price(price, currency: str | None) -> str:
    code = (currency or os.getenv("ALI_TARGET_CURRENCY", "USD") or "USD").strip().upper()
    symbol = CURRENCY_SYMBOLS.get(code)
    return f"{price}{symbol}" if symbol else f"{price} {code}"


def price_line(p: dict) -> str:
    currency = p.get("target_sale_price_currency")
    sale = p.get("target_sale_price") or "N/A"
    line = format_price(sale, currency)
    discount = p.get("__discount", 0)
    original = p.get("target_original_price")
    if discount >= 1 and original:
        line += f" (במקום {format_price(original, p.get('target_original_price_currency') or currency)}, {discount:.0f}% הנחה)"
    return line


def normalize_button_text(text: str) -> str:
    normalized = text.strip().lower()
    for token in ["🔥", "👟", "⌚", "📱"]:
        normalized = normalized.replace(token, "")
    return " ".join(normalized.split())


def is_generic_aliexpress_link(link: str) -> bool:
    if not link:
        return True

    normalized = link.strip().lower()
    if not normalized:
        return True

    parsed = urlparse(normalized)
    host = (parsed.netloc or "").lower()

    if "best.aliexpress.com" in host:
        return True

    if normalized in {
        "https://www.aliexpress.com",
        "https://www.aliexpress.com/",
        "https://aliexpress.com",
        "https://aliexpress.com/",
        "https://best.aliexpress.com",
        "https://best.aliexpress.com/",
    }:
        return True

    return False


def pick_best_product_link(product: dict) -> str:
    # Try multiple API fields and skip generic landing pages.
    candidates = [
        product.get("promotion_link"),
        product.get("product_detail_url"),
        product.get("detail_url"),
        product.get("product_url"),
        product.get("url"),
    ]

    for raw in candidates:
        if not raw:
            continue
        link = str(raw).strip()
        if not is_generic_aliexpress_link(link):
            return link

    return "N/A"


REVIEW_COUNT_KEYS = ["review_count", "reviews", "feedback_count", "evaluate_count", "comment_count"]
TRADE_COUNT_KEYS = ["lastest_volume", "trade_count", "orders", "order_count", "sale_count", "sold_count", "volume"]


def product_title(p: dict) -> str:
    return p.get("__title") or p.get("title") or p.get("product_title") or p.get("productTitle", "")


def annotate_product(p: dict, keyword_words: list[str], hot_products_requested: bool) -> dict:
    """Compute the ranking metrics (stored on the product as __* keys) and return the product."""
    title = product_title(p)
    p["__title"] = title
    p["__relevance"] = search_relevance_score(title, keyword_words) if not hot_products_requested else 0.0
    p["__rate"] = pick_best_rate(p)
    p["__review_count"] = pick_best_count(p, REVIEW_COUNT_KEYS)
    p["__trade_count"] = pick_best_count(p, TRADE_COUNT_KEYS)
    p["__total_sales"] = max(p["__review_count"], p["__trade_count"])
    return p


async def ensure_affiliate_links(products: list[dict]) -> None:
    missing = {}
    for p in products:
        if not p.get("promotion_link") or is_generic_aliexpress_link(str(p.get("promotion_link"))):
            url = product_page_url(p)
            if url:
                missing[url] = p
    if not missing:
        return
    links = await generate_affiliate_links(list(missing))
    for url, p in missing.items():
        if url in links:
            p["promotion_link"] = links[url]
        else:
            print(f"No affiliate link for {url}, using the plain product link")


def chunk_html_messages(parts: list[str], limit: int = 4096) -> list[str]:
    chunks: list[str] = []
    current = ""

    for part in parts:
        candidate = part if not current else f"{current}\n\n{part}"
        if len(candidate) <= limit:
            current = candidate
            continue

        if current:
            chunks.append(current)

        if len(part) <= limit:
            current = part
        else:
            chunks.append(part[:limit])
            current = ""

    if current:
        chunks.append(current)

    return chunks

class StageTimer:
    """Measures how long each stage of a search takes; logged as one TIMING line."""

    def __init__(self):
        self.start = self.last = time.monotonic()
        self.stages: dict[str, float] = {}

    def mark(self, stage: str) -> None:
        now = time.monotonic()
        self.stages[stage] = round(now - self.last, 2)
        self.last = now

    def log(self, query: str) -> None:
        total = round(time.monotonic() - self.start, 2)
        print("TIMING:", json.dumps({"query": query, **self.stages, "total": total}, ensure_ascii=False))


_SIZE_SUFFIX = re.compile(r"_\d+x\d+", re.IGNORECASE)


def small_image_url(url: str) -> str:
    """AliExpress CDN images accept a size suffix (e.g. ..._350x350.jpg).
    Telegram downloads every album image itself, so smaller images mean a
    faster album. Only applied to plain .jpg/.jpeg URLs on alicdn.com."""
    if not url:
        return url
    parsed = urlparse(url)
    path = parsed.path.lower()
    if "alicdn.com" in (parsed.netloc or "") and path.endswith((".jpg", ".jpeg")) \
            and not _SIZE_SUFFIX.search(path) and not parsed.query:
        return url + "_350x350.jpg"
    return url


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    timer = StageTimer()
    try:
        await _handle_message(update, context, timer)
    finally:
        timer.log(update.message.text.strip() if update.message and update.message.text else "")


async def _handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE, timer: StageTimer):
    text = update.message.text.strip()
    chat_id = update.message.chat.id

    normalized_text = normalize_button_text(text)
    hot_products_requested = normalized_text in {"מוצרים חמים", "hot products", "hotproducts"}
    button_query_config = BUTTON_QUERY_MAP.get(normalized_text)

    if hot_products_requested:
        ack_text = "🔥 מביא לך עכשיו מוצרים חמים מ-AliExpress..."
    elif button_query_config:
        ack_text = f"🔥 מביא עכשיו מוצרים חמים עבור: {normalized_text}"
    else:
        ack_text = f"🔍 מחפש את '{text}' באלי אקספרס..."
    # Send the "searching..." message while translating/searching, not before.
    # It is awaited before any other message so the order stays the same.
    ack = asyncio.create_task(update.message.reply_text(ack_text))

    translation_provider = "original"
    translation_comparison = {}
    quick_category_ids = None
    force_query = False
    if hot_products_requested:
        translated_text = "hot products"
    elif button_query_config:
        translated_text = button_query_config["keywords"]
        quick_category_ids = os.getenv(button_query_config["category_env"], "").strip() or None
        # If hot products by category returns nothing, fallback can still use product.query with category filter.
        force_query = False
    elif is_hebrew(text):
        translated_text, translation_provider, translation_comparison = await translate_to_english_with_debug(text)
        timer.mark("translate_query")
        if translation_provider == "none":
            await ack
            # Searching AliExpress with the raw Hebrew text returns random products.
            print(f"Translation failed for query: {text}")
            await update.message.reply_text(
                "⚠️ שירות התרגום עמוס כרגע ולא הצלחתי לתרגם את החיפוש. "
                "נסה שוב בעוד דקה, או כתוב את שם המוצר באנגלית."
            )
            return
    else:
        translated_text = text

    keyword_words = tokenize(translated_text)

    compare_debug = os.getenv("ALI_COMPARE_SEARCH_DEBUG", "0").strip().lower() in {"1", "true", "yes", "on"}
    search_compare = None
    if compare_debug and not hot_products_requested:
        search_compare = await compare_search_methods(
            keywords=translated_text,
            page_no=1,
            page_size=50,
            category_ids=quick_category_ids,
        )
        print(f"ALI_SEARCH_COMPARE: {search_compare}")

    if hot_products_requested:
        data, search_method = await fetch_hot_products(page_no=1, page_size=50)
    elif button_query_config:
        data, search_method = await fetch_hot_products(
            page_no=1,
            page_size=50,
            category_ids=quick_category_ids,
            keywords=translated_text,
        )
        hot_button_products = find_products_in_response(data) or []
        if not hot_button_products:
            data, search_method = await search_products_with_fallback(
                keywords=translated_text,
                page_no=1,
                page_size=50,
                category_ids=quick_category_ids,
                force_query=bool(quick_category_ids),
            )
    else:
        data, search_method = await search_products_with_fallback(
            keywords=translated_text,
            page_no=1,
            page_size=50,
            category_ids=quick_category_ids,
            force_query=force_query,
        )
    print(f"ALI_SEARCH_METHOD: {search_method}")
    timer.mark("search")
    await ack

    # Keep a full per-search log (original query + translation + raw API response)
    log_search(
        text,
        translated_text,
        data,
        translation_provider=translation_provider,
        translation_comparison=translation_comparison,
        search_method=search_method,
        search_compare=search_compare,
    )

    products = find_products_in_response(data)
    if not products:
        api_error = get_api_error(data)
        if api_error:
            print(f"ALI_API_ERROR ({search_method}): {api_error}")
        if api_error and ("error_response" in data or "error" in data):
            # The request itself failed (bad keys/signature, network...), not an empty result.
            await update.message.reply_text("⚠️ שגיאה בחיבור ל-AliExpress. נסה שוב בעוד כמה דקות.")
        else:
            await update.message.reply_text("❌ לא נמצאו מוצרים.")
        return

    filtered = []
    for p in products:
        title = product_title(p)

        if not hot_products_requested and not match_search_words(title, keyword_words):
            continue

        filtered.append(annotate_product(p, keyword_words, hot_products_requested))

    if not filtered and not hot_products_requested:
        # Only products that match at least one search word; never random products.
        fallback_ranked = [
            p for p in (annotate_product(p, keyword_words, hot_products_requested) for p in products)
            if p["__relevance"] > 0
        ]
        if not fallback_ranked:
            await update.message.reply_text("❌ לא נמצאו מוצרים מתאימים לחיפוש. נסה לנסח אחרת.")
            return
        await update.message.reply_text("⚠️ לא נמצאו תוצאות מדויקות, מציג את התוצאות הקרובות ביותר:")
        filtered = rank_products(fallback_ranked, min_rating=0)[:10]

    # Enrich all current candidates first, then rank with the enriched metrics.
    # This avoids picking an arbitrary top-5 when initial API response has zeros/nulls.
    enriched_candidates = await enrich_products_with_details(filtered)
    timer.mark("enrich")

    # Re-apply metric extraction after enrichment
    for p in enriched_candidates:
        annotate_product(p, keyword_words, hot_products_requested)

    # Most relevant first, then best combination of rating, sales and discount.
    top5 = rank_products(enriched_candidates)[:5]

    # Both at once:
    # - every product should link through the affiliate account; products the
    #   search returned without promotion_link get one from link.generate;
    # - all titles are translated in one request (separate requests hit
    #   Google's rate limit).
    _, translated_titles = await asyncio.gather(
        ensure_affiliate_links(top5),
        translate_titles_to_hebrew([p.get("__title", "") for p in top5]),
    )
    timer.mark("links_and_titles")

    images = []
    captions = []
    for p, translated_title in zip(top5, translated_titles):
        title = p.get("__title", "")
        image = p.get("product_main_image_url") or p.get("image_url")
        link = pick_best_product_link(p)
        rate = p.get("__rate", "N/A")

        trade_count = p.get('__trade_count', 0)

        metrics = []
        if rate:
            metrics.append(f"⭐ דירוג: {rate}%")
        if trade_count:
            metrics.append(f"🛍️ כמות הזמנות: {trade_count}")
        metrics_line = " | ".join(metrics) if metrics else "📊 אין נתוני מכירות"

        short_title = translated_title.strip()
        if len(short_title) > 90:
            short_title = short_title[:87].rstrip() + "..."

        message_part = (
            f"{short_title}\n"
            f"מחיר: {price_line(p)}\n"
            f"{metrics_line}\n"
            f"🔗 קישור למוצר"
        )
        captions.append((message_part, link))
        if image:
            images.append((image, short_title))

    if images:
        try:
            await context.bot.send_media_group(
                chat_id=chat_id,
                media=[InputMediaPhoto(media=small_image_url(img), caption=cap) for img, cap in images],
            )
        except Exception as e:
            print("שגיאה באלבום (תמונות מוקטנות), מנסה עם התמונות המקוריות:", e)
            try:
                await context.bot.send_media_group(
                    chat_id=chat_id,
                    media=[InputMediaPhoto(media=img, caption=cap) for img, cap in images],
                )
            except Exception as e2:
                print("שגיאה באלבום:", e2)
        timer.mark("album")

    html_parts = []
    for part, link in captions:
        safe_part = escape(part)
        if link and link != "N/A":
            safe_link = escape(link, quote=True)
            safe_part = safe_part.replace("קישור למוצר", f"<a href=\"{safe_link}\">קישור למוצר</a>")
        html_parts.append(safe_part)

    message_html = "\n\n".join(html_parts)
    try:
        await update.message.reply_text(
            message_html,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
    except Exception as e:
        print("שגיאה בשליחת הודעת קישורים:", e)
        plain_text = message_html.replace("<a href=\"", "").replace("\">קישור למוצר</a>", "קישור למוצר")
        await update.message.reply_text(plain_text, disable_web_page_preview=True)
    timer.mark("text_message")
