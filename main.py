from telegram import Update, InputMediaPhoto
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
import os
from flask import Flask
import threading

# 1. Render의 포트 체크를 통과하기 위한 가짜 웹 서버 (Flask)
flask_app = Flask(__name__)

@flask_app.route('/')
def health_check():
    return "I am alive!", 200

def run_flask():
    # Render는 기본적으로 10000번 포트를 체크합니다.
    port = int(os.environ.get("PORT", 10000))
    flask_app.run(host='0.0.0.0', port=port)

# 2. 텔레그램 봇 설정
TOKEN = os.getenv("TOKEN")

async def event(update: Update, context: ContextTypes.DEFAULT_TYPE):
    event_caption = (
        "이벤트 문의는 아래 양식으로만 접수합니다.\n\n"
        "양식에 맞추지 않고 작성한 문의건은 처리 불가하며...\n"
        "💕사이트 이벤트 = 사이트 고객센터\n"
        "💕가족방 이벤트 = 연합총장.SITE 💕"
    )
    
    media = [
        InputMediaPhoto("AAMCBQADGQEDCmM_aesGnHT0ask7yVmTxXnB6Xn1y_kAApobAAI2XFhXpj2CcTONJP4BAAdtAAM7BA", caption=event_caption),
        InputMediaPhoto("AAMCBQADGQEDCmNAaesGnIAW3-pmeSScoCJxL432ZMEAApsbAAI2XFhXIGKgBn8d8IgBAAdtAAM7BA"),
        InputMediaPhoto("AAMCBQADGQEDCmNBaesGnKx5XT8a8E8Ga2RUJa7F6qUAApwbAAI2XFhXtyweiMmGAzMBAAdtAAM7BA"),
        InputMediaPhoto("AAMCBQADGQEDCmNEaesGnA2IEzOqZHOW0Rq_gLDDEEQAAp4bAAI2XFhXarAfDgUPRYABAAdtAAM7BA"),
        InputMediaPhoto("AAMCBQADGQEDCmNCaesGnI3joyM55Ye_XK13JKnhEdAAAp0bAAI2XFhXOBuF4qvBraYBAAdtAAM7BA"),
        InputMediaPhoto("AAMCBQADGQEDCmNFaesGnMUIsu7Fq3vgwk-kGtA8Gq4AAp8bAAI2XFhXx5RCEgxM-ZIBAAdtAAM7BA"),
        InputMediaPhoto("AAMCBQADGQEDCmNHaesGnDm__uZofB5SJUc9bvL96TkAAqAbAAI2XFhXlfI9-oVRJBcBAAdtAAM7BA"),
    ]
    await update.message.reply_media_group(media)

if __name__ == "__main__":
    if not TOKEN:
        print("TOKEN이 없습니다.")
    else:
        # 가짜 웹 서버를 백그라운드(스레드)에서 실행
        threading.Thread(target=run_flask, daemon=True).start()
        
        # 텔레그램 봇 실행
        app = ApplicationBuilder().token(TOKEN).build()
        app.add_handler(CommandHandler("이벤트", event))
        print("뜌리봇 무료 모드 실행 중...")
        app.run_polling()
