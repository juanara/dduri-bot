from telegram import Update, InputMediaPhoto
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
import os
from flask import Flask
import threading

flask_app = Flask(__name__)

@flask_app.route('/')
def health_check():
    return "Bot is running!", 200

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    flask_app.run(host='0.0.0.0', port=port)

TOKEN = os.getenv("TOKEN")

async def event(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # 텍스트가 "/이벤트"로 시작할 때만 작동하도록 합니다.
    if update.message and update.message.text and update.message.text.startswith("/이벤트"):
        event_caption = (
            "이벤트 문의는 아래 양식으로만 접수합니다.\n\n"
            "양식에 맞추지 않고 작성한 문의건은 처리 불가하며...\n\n"
            "💕사이트 이벤트 = 사이트 고객센터\n"
            "💕가족방 이벤트 = 연합총장.SITE 💕"
        )
        
        media = [
            InputMediaPhoto("AgACAgUAAxkBAAMRaesMN3B7oN3YzpO1uPXxx7c_TNQAAn0PaxvK_FlXDpCkEHDNt5kBAAMCAAN5AAM7BA", caption=event_caption, parse_mode="HTML"),
            InputMediaPhoto("AgACAgUAAxkBAAMSaesMN7_uf8oG0cHblQWTUCh8ftQAAn4PaxvK_FlXFI0GlnCjyQgBAAMCAAN5AAM7BA"),
            InputMediaPhoto("AgACAgUAAxkBAAMTaesMN7wqlQe0HY_Id-VIu-WVfiEAAn8PaxvK_FlXuKpKlA_IjnIBAAMCAAN5AAM7BA"),
            InputMediaPhoto("AgACAgUAAxkBAAMUaesMN60FX6XjnC99nHolHgRvSWEAAoAPaxvK_FlXAAGK-TvCzezgAQADAgADeQADOwQ"),
            InputMediaPhoto("AgACAgUAAxkBAAMVaesMN_pU8B4jl2g6IUCnIthgHcsAAoEPaxvK_FlXZW0NWBXSj40BAAMCAAN5AAM7BA"),
            InputMediaPhoto("AgACAgUAAxkBAAMWaesMNy5PWpPTvJyA61CztjglWcYAAoIPaxvK_FlX0gi06hvNXv0BAAMCAAN5AAM7BA"),
            InputMediaPhoto("AgACAgUAAxkBAAMQaesMN9rfjcwJ8rnfK4c9S71_CEgAAnwPaxvK_FlX_tyL1jbI-yoBAAMCAAN5AAM7BA"),
        ]
        
        try:
            await update.message.reply_media_group(media)
        except Exception as e:
            print(f"Error: {e}")

if __name__ == "__main__":
    if TOKEN:
        threading.Thread(target=run_flask, daemon=True).start()
        app = ApplicationBuilder().token(TOKEN).build()
        
        # CommandHandler 대신 MessageHandler를 사용해 한글 "/이벤트"를 감지합니다.
        app.add_handler(MessageHandler(filters.TEXT & filters.COMMAND, event))
        # 혹시 모르니 숫자 명령어 /1 도 남겨둡니다.
        app.add_handler(CommandHandler("1", event))
        
        app.run_polling()
