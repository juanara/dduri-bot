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
    # 사용자가 /이벤트 또는 /1을 입력했을 때만 작동
    if update.message and update.message.text and (update.message.text.startswith("/이벤트") or update.message.text.startswith("/1")):
        
        # 요청하신 전체 문구 (한 글자도 빠짐없이 넣었습니다)
        event_caption = (
            "이벤트 문의는 아래 양식으로만 접수합니다.\n\n"
            "양식에 맞추지 않고 작성한 문의건은 처리 불가하며, 앞으로 양식 미준수 건은 자동 참여불가 처리합니다.\n\n"
            " 번거로우시더라도 원활한 처리를 위해 반드시 지켜주시기 바랍니다.\n\n"
            "사이트 :\n"
            "닉네임 :\n"
            "참여금액 :\n"
            "이벤트내용 :\n\n"
            "※ 첫충/매충 등 동일인이 여러 이벤트를 신청할 경우, 이벤트별로 각각 작성해 주세요.\n\n"
            "예)\n"
            "이벤트1.\n"
            "사이트 :\n"
            "닉네임 :\n"
            "참여금액 :\n"
            "이벤트내용 :\n\n"
            "이벤트2.\n"
            "사이트 :\n"
            "닉네임 :\n"
            "참여금액 :\n"
            "이벤트내용 :\n\n"
            " 양식 미준수(예: “이벤트주세요”, “참여요” 등 간단 문의)는 접수 불가합니다. \n\n"
            " 반복 안내 후에도 양식 미준수 시 향후 이벤트 참여 제한이 있을 수 있으니 협조 부탁드립니다. ☺️\n\n\n"
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
        
        # 한글 명령어 처리를 위한 핸들러
        app.add_handler(MessageHandler(filters.TEXT & filters.COMMAND, event))
        # 숫자 /1 도 작동하도록 유지
        app.add_handler(CommandHandler("1", event))
        
        app.run_polling()
