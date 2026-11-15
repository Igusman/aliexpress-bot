from dotenv import load_dotenv
import os
import sys
from telegram.ext import Application, CommandHandler, MessageHandler, filters
from handlers.commands import start_command, help_command
from handlers.messages import handle_message
from services.utils import error_handler

load_dotenv()
TOKEN = os.getenv("TOKEN")

if __name__ == "__main__":
    if not TOKEN:
        sys.exit("ERROR: TOKEN environment variable is not set (Telegram bot token). Exiting.")
    missing_ali = [v for v in ("ALIEXPRESS_APP_KEY", "ALIEXPRESS_APP_SECRET") if not os.getenv(v)]
    if missing_ali:
        print(f"WARNING: {', '.join(missing_ali)} not set - AliExpress searches will fail.")

    # concurrent_updates: handle several users at once instead of queueing them.
    app = Application.builder().token(TOKEN).concurrent_updates(True).build()
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_error_handler(error_handler)
    app.run_polling()