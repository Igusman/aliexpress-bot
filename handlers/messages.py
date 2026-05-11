import time
import json
from telegram import Update, InputMediaPhoto
from telegram.ext import ContextTypes
from services.translation import is_hebrew, translate_to_english, translate_to_hebrew
from services.aliexpress_api import call_aliexpress_sync_api, find_products_in_response
from services.logging import log_search
from services.utils import tokenize, match_search_words, shorten_url

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    start_time = time.time()
    text = update.message.text.strip()
    chat_id = update.message.chat.id
    await update.message.reply_text(f"🔍 מחפש את '{text}' באלי אקספרס...")

    translated_text = await translate_to_english(text) if is_hebrew(text) else text
    keyword_words = tokenize(translated_text)
    log_search(text, translated_text)

    data = await call_aliexpress_sync_api("aliexpress.affiliate.product.query", {
        "page_no": 1,
        "page_size": 20,
        "keywords": translated_text
    })

    products = find_products_in_response(data)
    if not products:
        await update.message.reply_text("❌ לא נמצאו מוצרים.")
        return

    # DEBUG: Print first 2 complete products as JSON
    print("\n" + "="*100)
    print("🔍 ALIEXPRESS API RESPONSE - First 2 Products (Complete JSON):")
    print("="*100)
    for idx, p in enumerate(products[:2]):
        print(f"\n📦 Product {idx + 1}:")
        print(json.dumps(p, indent=2, ensure_ascii=False))
    print("\n" + "="*100 + "\n")

    filtered = []
    for p in products:
        title = p.get("title") or p.get("product_title") or p.get("productTitle", "")

    if not filtered:
        await update.message.reply_text("⚠️ לא נמצאו תוצאות מדויקות, מציג הצעות כלליות:")
        filtered = products[:3]
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
