from telegram import Update, InputMediaPhoto
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
import os
from flask import Flask
import threading

# Render의 포트 체크를 통과하기 위한 가짜 웹 서버 (Flask)
flask_app = Flask(__name__)

@flask_app.route('/')
def health_check():
    return "Bot is running!", 200

def run_flask():
    # Render는 무료 Web Service의 경우 10000번 포트를 체크합니다.
    port = int(os.environ.get("PORT", 10000))
    flask_app.run(host='0.0.0.0', port=port)

# 텔레그램 봇 토큰 설정
TOKEN = os.getenv("TOKEN")

async def event(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # 요청하신 이벤트 공지 문구
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
        print("에러: TOKEN 환경 변수가 없습니다.")
    else:
        # 가짜 웹 서버 실행 (Render 중단 방지)
        threading.Thread(target=run_flask, daemon=True).start()
        
        # 봇 실행
        app = ApplicationBuilder().token(TOKEN).build()
        
        # '이벤트' 대신 '1' 로 명령어 변경
        app.add_handler(CommandHandler("1", event))
        
        print("뜌리봇 무료 모드 실행 중...")
        app.run_polling()
