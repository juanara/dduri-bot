from telegram import Update, InputMediaPhoto
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
import os

TOKEN = os.getenv("TOKEN")

async def event(update: Update, context: ContextTypes.DEFAULT_TYPE):
    media = [
        InputMediaPhoto("이미지1", caption="🔥 VIP 이벤트 🔥"),
        InputMediaPhoto("이미지2"),
        InputMediaPhoto("이미지3"),
        InputMediaPhoto("이미지4"),
        InputMediaPhoto("이미지5"),
        InputMediaPhoto("이미지6"),
        InputMediaPhoto("이미지7"),
    ]
    await update.message.reply_media_group(media)

app = ApplicationBuilder().token(TOKEN).build()
app.add_handler(CommandHandler("이벤트", event))

app.run_polling()