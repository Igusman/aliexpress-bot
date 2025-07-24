from telegram import Update
from telegram.ext import ContextTypes

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("שלום! שלח שם מוצר ואני אחפש לך באלי אקספרס.")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("פשוט שלח שם מוצר (לדוגמה: smartwatch) ואחזיר לך הצעות.")
