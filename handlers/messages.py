import time
import os
from html import escape
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

        if link != "N/A":
            safe_link_href = escape(link, quote=True)
            safe_link_text = escape(link)
            link_line = f"🔗 <a href=\"{safe_link_href}\">{safe_link_text}</a>"
        else:
            link_line = "🔗 N/A"

        caption = (
            f"<b>{translated_title}</b>\n"
            f"מחיר: <b>{sale_price}$</b>\n"
            f"{metrics_line}\n"
            f"{link_line}"
        )
        captions.append(caption)
        if image:
            media_group.append(InputMediaPhoto(media=image, caption=title[:100]))

    if media_group:
        try:
            await context.bot.send_media_group(chat_id=chat_id, media=media_group)
        except Exception as e:
            print("שגיאה באלבום:", e)

    await update.message.reply_text(
        "\n\n".join(captions)[:4096],
        parse_mode="HTML",
        disable_web_page_preview=True,
    )
    print("⏱️ זמן טיפול:", f"{time.time() - start_time:.2f} שניות")
