from dotenv import load_dotenv
import os
from telegram.ext import Application, CommandHandler, MessageHandler, filters
from handlers.commands import start_command, help_command
from handlers.messages import handle_message
from services.utils import error_handler

load_dotenv()
TOKEN = os.getenv("TOKEN")

if __name__ == "__main__":
    # concurrent_updates: handle several users at once instead of queueing them.
    app = Application.builder().token(TOKEN).concurrent_updates(True).build()
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_error_handler(error_handler)
    app.run_polling()