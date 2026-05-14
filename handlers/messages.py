import time
from telegram import Update, InputMediaPhoto
from telegram.ext import ContextTypes
from services.translation import is_hebrew, translate_to_english_with_debug, translate_to_hebrew
from services.aliexpress_api import (
    build_product_query_params,
    call_aliexpress_sync_api,
    find_products_in_response,
    pick_best_count,
    pick_best_rate,
)
from services.logging import log_search
from services.utils import tokenize, match_search_words, shorten_url

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

        p["__rate"] = pick_best_rate(p)
        p["__review_count"] = pick_best_count(
            p,
            ["review_count", "reviews", "feedback_count", "evaluate_count", "comment_count"],
        )
        p["__trade_count"] = pick_best_count(
            p,
            ["trade_count", "orders", "order_count", "sale_count", "sold_count", "volume"],
        )
        p["__total_sales"] = max(p["__review_count"], p["__trade_count"])
        p["__title"] = title
        filtered.append(p)

    if not filtered:
        await update.message.reply_text("⚠️ לא נמצאו תוצאות מדויקות, מציג הצעות כלליות:")
        filtered = products[:3]

        for p in filtered:
            p["__rate"] = pick_best_rate(p)
            p["__review_count"] = pick_best_count(
                p,
                ["review_count", "reviews", "feedback_count", "evaluate_count", "comment_count"],
            )
            p["__trade_count"] = pick_best_count(
                p,
                ["trade_count", "orders", "order_count", "sale_count", "sold_count", "volume"],
            )
            p["__total_sales"] = max(p["__review_count"], p["__trade_count"])
            p["__title"] = p.get("title") or p.get("product_title") or p.get("productTitle", "")

    # Sort by total sales first, then by rating
    filtered.sort(key=lambda x: (-x.get("__total_sales", 0), -x.get("__rate", 0.0)))

    media_group = []
    captions = []
    for p in filtered[:5]:
        title = p.get("__title", "")
        image = p.get("product_main_image_url") or p.get("image_url")
        link = p.get("promotion_link") or "N/A"
        short_link = shorten_url(link)
        original_price = p.get("target_original_price") or "N/A"
        sale_price = p.get("target_sale_price") or "N/A"
        rate = p.get("__rate", "N/A")
        translated_title = await translate_to_hebrew(title)

        caption = (
            f"<b>{translated_title}</b>\n"
            f"מחיר: <b>{sale_price}$</b>\n"
            f"⭐ דירוג: {rate}% | 📦 ביקורות: {p.get('__review_count', 0)} | 🛍️ עסקאות: {p.get('__trade_count', 0)}\n"
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
