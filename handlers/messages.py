import time
import os
from html import escape
from urllib.parse import urlparse
from telegram import Update, InputMediaPhoto
from telegram.ext import ContextTypes
from services.translation import is_hebrew, translate_to_english_with_debug, translate_to_hebrew
from services.aliexpress_api import (
    compare_search_methods,
    enrich_products_with_details,
    fetch_hot_products,
    find_products_in_response,
    pick_best_count,
    pick_best_rate,
    search_products_with_fallback,
)
from services.logging import log_search
from services.utils import tokenize, match_search_words, search_relevance_score

BUTTON_QUERY_MAP = {
    "נעליים": {"keywords": "shoes", "category_env": "ALI_CATEGORY_SHOES"},
    "שעון חכם": {"keywords": "smart watch", "category_env": "ALI_CATEGORY_SMARTWATCH"},
    "אקססוריז טלפון": {"keywords": "phone accessories", "category_env": "ALI_CATEGORY_PHONE_ACCESSORIES"},
}


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

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    start_time = time.time()
    text = update.message.text.strip()
    chat_id = update.message.chat.id

    normalized_text = normalize_button_text(text)
    hot_products_requested = normalized_text in {"מוצרים חמים", "hot products", "hotproducts"}
    button_query_config = BUTTON_QUERY_MAP.get(normalized_text)

    if hot_products_requested:
        await update.message.reply_text("🔥 מביא לך עכשיו מוצרים חמים מ-AliExpress...")
    elif button_query_config:
        await update.message.reply_text(f"🔥 מביא עכשיו מוצרים חמים עבור: {normalized_text}")
    else:
        await update.message.reply_text(f"🔍 מחפש את '{text}' באלי אקספרס...")

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
    else:
        translated_text = text

    keyword_words = tokenize(translated_text)

    compare_debug = os.getenv("ALI_COMPARE_SEARCH_DEBUG", "0").strip().lower() in {"1", "true", "yes", "on"}
    search_compare = None
    if compare_debug and not hot_products_requested:
        search_compare = await compare_search_methods(
            keywords=translated_text,
            page_no=1,
            page_size=20,
            category_ids=quick_category_ids,
        )
        print(f"ALI_SEARCH_COMPARE: {search_compare}")

    if hot_products_requested:
        data, search_method = await fetch_hot_products(page_no=1, page_size=20)
    elif button_query_config:
        data, search_method = await fetch_hot_products(
            page_no=1,
            page_size=20,
            category_ids=quick_category_ids,
            keywords=translated_text,
        )
        hot_button_products = find_products_in_response(data) or []
        if not hot_button_products:
            data, search_method = await search_products_with_fallback(
                keywords=translated_text,
                page_no=1,
                page_size=20,
                category_ids=quick_category_ids,
                force_query=bool(quick_category_ids),
            )
    else:
        data, search_method = await search_products_with_fallback(
            keywords=translated_text,
            page_no=1,
            page_size=20,
            category_ids=quick_category_ids,
            force_query=force_query,
        )
    print(f"ALI_SEARCH_METHOD: {search_method}")

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
        await update.message.reply_text("❌ לא נמצאו מוצרים.")
        return

    filtered = []
    for p in products:
        title = p.get("title") or p.get("product_title") or p.get("productTitle", "")

        if not hot_products_requested and not match_search_words(title, keyword_words):
            continue

        p["__relevance"] = search_relevance_score(title, keyword_words) if not hot_products_requested else 0.0
        p["__rate"] = pick_best_rate(p)
        p["__review_count"] = pick_best_count(
            p,
            ["review_count", "reviews", "feedback_count", "evaluate_count", "comment_count"],
        )
        p["__trade_count"] = pick_best_count(
            p,
            ["lastest_volume", "trade_count", "orders", "order_count", "sale_count", "sold_count", "volume"],
        )
        p["__total_sales"] = max(p["__review_count"], p["__trade_count"])
        p["__title"] = title
        filtered.append(p)

    if not filtered and not hot_products_requested:
        await update.message.reply_text("⚠️ לא נמצאו תוצאות מדויקות, מציג הצעות כלליות:")
        fallback_ranked = []
        for p in products:
            title = p.get("title") or p.get("product_title") or p.get("productTitle", "")
            p["__relevance"] = search_relevance_score(title, keyword_words)
            p["__rate"] = pick_best_rate(p)
            p["__review_count"] = pick_best_count(
                p,
                ["review_count", "reviews", "feedback_count", "evaluate_count", "comment_count"],
            )
            p["__trade_count"] = pick_best_count(
                p,
                ["lastest_volume", "trade_count", "orders", "order_count", "sale_count", "sold_count", "volume"],
            )
            p["__total_sales"] = max(p["__review_count"], p["__trade_count"])
            p["__title"] = title
            fallback_ranked.append(p)

        fallback_ranked.sort(key=lambda x: (-x.get("__relevance", 0.0), -x.get("__total_sales", 0), -x.get("__rate", 0.0)))
        filtered = fallback_ranked[:10]

    # Enrich all current candidates first, then rank with the enriched metrics.
    # This avoids picking an arbitrary top-5 when initial API response has zeros/nulls.
    enriched_candidates = await enrich_products_with_details(filtered)

    # Re-apply metric extraction after enrichment
    for p in enriched_candidates:
        title = p.get("__title") or p.get("title") or p.get("product_title") or p.get("productTitle", "")
        p["__relevance"] = search_relevance_score(title, keyword_words) if not hot_products_requested else 0.0
        p["__review_count"] = pick_best_count(
            p, ["review_count", "reviews", "feedback_count", "evaluate_count", "comment_count"]
        )
        p["__trade_count"] = pick_best_count(
            p, ["lastest_volume", "trade_count", "orders", "order_count",
                "sale_count", "sold_count", "volume"]
        )
        p["__total_sales"] = max(p.get("__review_count", 0), p.get("__trade_count", 0))
        p["__rate"] = pick_best_rate(p)

    # Sort by relevance first, then by sales and rating.
    enriched_candidates.sort(
        key=lambda x: (-x.get("__relevance", 0.0), -x.get("__total_sales", 0), -x.get("__rate", 0.0))
    )
    top5 = enriched_candidates[:5]

    media_group = []
    captions = []
    for p in top5:
        title = p.get("__title", "")
        image = p.get("product_main_image_url") or p.get("image_url")
        link = p.get("promotion_link") or "N/A"
        original_price = p.get("target_original_price") or "N/A"
        sale_price = p.get("target_sale_price") or "N/A"
        rate = p.get("__rate", "N/A")
        translated_title = await translate_to_hebrew(title)

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
            f"מחיר: {sale_price}$\n"
            f"{metrics_line}\n"
            f"🔗 קישור למוצר"
        )
        captions.append((message_part, link))
        if image:
            media_group.append(InputMediaPhoto(media=image, caption=title[:100]))

    if media_group:
        try:
            await context.bot.send_media_group(chat_id=chat_id, media=media_group)
        except Exception as e:
            print("שגיאה באלבום:", e)

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
    print("⏱️ זמן טיפול:", f"{time.time() - start_time:.2f} שניות")
