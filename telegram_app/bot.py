"""Telegram entry bot that opens the Mini App."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, WebAppInfo
from telegram.ext import Application, CommandHandler, ContextTypes


async def start(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    app_url = os.environ["APP_URL"]
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("Відкрити додаток", web_app=WebAppInfo(app_url))]])
    await update.effective_message.reply_text("Керуйте своїм локальним агентом у додатку.", reply_markup=keyboard)


def main() -> None:
    load_dotenv(Path(__file__).parent / "settings.env")
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", start))
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
