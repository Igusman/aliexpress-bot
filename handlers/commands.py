from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import ContextTypes

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_message = (
        "🎉 ברוכים הבאים לבוט חיפוש AliExpress!\n\n"
        "🔍 אני כאן כדי לעזור לך למצוא מוצרים באלי אקספרס.\n\n"
        "📝 פשוט כתוב את שם המוצר שאתה מחפש (לדוגמה: smartwatch, נעליים, חולצה) "
        "ואני אחזיר לך את התוצאות הטובות ביותר עם מחירים ודירוגים.\n\n"
        "💡 טיפים:\n"
        "• תוכל לכתוב בעברית או אנגלית\n"
        "• אני אתרגם בעצמי לאנגלית כדי למצוא מוצרים\n"
        "• כל מוצר יציג מחיר, דירוג ומספר הזמנות\n\n"
        "👇 מה אתה מחפש?"
    )
    
    keyboard = [
        ["👟 נעליים"],
        ["⌚ שעון חכם"],
        ["📱 אקססוריז טלפון"],
        ["🎮 ألعاب"],
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
    
    await update.message.reply_text(welcome_message, reply_markup=reply_markup)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📚 עזרה:\n\n"
        "1️⃣ שלח לי שם מוצר בעברית או אנגלית\n"
        "2️⃣ אני אחפש בAliExpress ותחזיר לך את התוצאות הטובות ביותר\n"
        "3️⃣ כל תוצאה תציג:\n"
        "   • שם המוצר (מתורגם לעברית)\n"
        "   • מחיר בדולר\n"
        "   • ⭐ דירוג (אם קיים)\n"
        "   • 🛍️ הזמנות בחודש האחרון (אם קיים)\n"
        "   • 🔗 קישור ישיר למוצר\n\n"
        "💬 שאל אותי כמה שאתה רוצה, בחופשיות!"
    )
