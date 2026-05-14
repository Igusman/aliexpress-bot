import time
from telegram import Update, InputMediaPhoto
from telegram.ext import ContextTypes
from services.translation import is_hebrew, translate_to_english_with_debug, translate_to_hebrew
from services.aliexpress_api import (
    build_product_query_params,
    call_aliexpress_sync_api,
    enrich_products_with_details,
    find_products_in_response,
    pick_best_count,
    pick_best_rate,
)
from services.logging import log_search
from services.utils import tokenize, match_search_words, search_relevance_score, shorten_url

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    start_time = time.time()
    text = update.message.text.strip()
    chat_id = update.message.chat.id
    await update.message.reply_text(f"🔍 מחפש את '{text}' באלי אקספרס...")

    translation_provider = "original"
    translation_comparison = {}
    if is_hebrew(text):
        translated_text, translation_provider, translation_comparison = await translate_to_english_with_debug(text)
    else:
        translated_text = text

    keyword_words = tokenize(translated_text)

    query_params = build_product_query_params(
        keywords=translated_text,
        page_no=1,
        page_size=20,
    )
    data = await call_aliexpress_sync_api("aliexpress.affiliate.product.query", query_params)

    # Keep a full per-search log (original query + translation + raw API response)
    log_search(
        text,
        translated_text,
        data,
        translation_provider=translation_provider,
        translation_comparison=translation_comparison,
    )

    products = find_products_in_response(data)
    if not products:
        await update.message.reply_text("❌ לא נמצאו מוצרים.")
        return

    filtered = []
    for p in products:
        title = p.get("title") or p.get("product_title") or p.get("productTitle", "")
        if not match_search_words(title, keyword_words):
            continue

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
        filtered.append(p)

    if not filtered:
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
        p["__relevance"] = search_relevance_score(title, keyword_words)
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
        short_link = shorten_url(link)
        original_price = p.get("target_original_price") or "N/A"
        sale_price = p.get("target_sale_price") or "N/A"
        rate = p.get("__rate", "N/A")
        translated_title = await translate_to_hebrew(title)

        trade_count = p.get('__trade_count', 0)

        metrics = []
        if rate:
            metrics.append(f"⭐ דירוג: {rate}%")
        if trade_count:
            metrics.append(f"🛍️ הזמנות (30 יום): {trade_count}")
        metrics_line = " | ".join(metrics) if metrics else "📊 אין נתוני מכירות"

        caption = (
            f"<b>{translated_title}</b>\n"
            f"מחיר: <b>{sale_price}$</b>\n"
            f"{metrics_line}\n"
            f"🔗 <a href=\"{short_link}\">קישור למוצר</a>"
        )
        captions.append(caption)
        if image:
            media_group.append(InputMediaPhoto(media=image, caption=title[:100]))

    if media_group:
        try:
            await context.bot.send_media_group(chat_id=chat_id, media=media_group)
        except Exception as e:
            print("שגיאה באלבום:", e)

    await update.message.reply_text("\n\n".join(captions)[:4096], parse_mode="HTML")
    print("⏱️ זמן טיפול:", f"{time.time() - start_time:.2f} שניות")
