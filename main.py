from telegram import Update, InputMediaPhoto
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
import os
from flask import Flask
import threading

# Render 포트 체크용 가짜 웹 서버
flask_app = Flask(__name__)

@flask_app.route('/')
def health_check():
    return "Bot is running!", 200

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    flask_app.run(host='0.0.0.0', port=port)

TOKEN = os.getenv("TOKEN")

async def event(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ▼ 이 부분에 이모지를 복사해서 넣으시면 움직이는 이모지도 그대로 나옵니다!
    event_caption = (
        "이벤트 문의는 아래 양식으로만 접수합니다.\n\n"
        "양식에 맞추지 않고 작성한 문의건은 처리 불가하며, 앞으로 양식 미준수 건은 자동 참여불가 처리합니다.\n\n"
        "번거로우시더라도 원활한 처리를 위해 반드시 지켜주시기 바랍니다.\n\n"
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
        "양식 미준수(예: “이벤트주세요”, “참여요” 등 간단 문의)는 접수 불가합니다.\n\n"
        "반복 안내 후에도 양식 미준수 시 향후 이벤트 참여 제한이 있을 수 있으니 협조 부탁드립니다. ☺️\n\n"
        "💕사이트 이벤트 = 사이트 고객센터\n"
        "💕가족방 이벤트 = 연합총장.SITE 💕"
    )
    
    # 사용자님이 방금 따오신 7개의 사진 ID입니다.
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
        await update.message.reply_text("❌ 메시지 전송 중 에러가 발생했습니다.")

if __name__ == "__main__":
    if TOKEN:
        threading.Thread(target=run_flask, daemon=True).start()
        app = ApplicationBuilder().token(TOKEN).build()
        
        # 명령어 /1 설정 (사진 ID 추출 기능은 뺐습니다!)
        app.add_handler(CommandHandler("이벤트", event))
        
        print("뜌리봇 이모지 지원 모드 실행 중...")
        app.run_polling()
