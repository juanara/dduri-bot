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
    
    # ★ 나중에 이 부분의 영어를 새로 받은 ID로 바꿔야 합니다! ★
    media = [
        InputMediaPhoto("AAMCBQADGQEDCmM_aesGnHT0ask7yVmTxXnB6Xn1y_kAApobAAI2XFhXpj2CcTONJP4BAAdtAAM7BA", caption=event_caption),
        InputMediaPhoto("AAMCBQADGQEDCmNAaesGnIAW3-pmeSScoCJxL432ZMEAApsbAAI2XFhXIGKgBn8d8IgBAAdtAAM7BA"),
        InputMediaPhoto("AAMCBQADGQEDCmNBaesGnKx5XT8a8E8Ga2RUJa7F6qUAApwbAAI2XFhXtyweiMmGAzMBAAdtAAM7BA"),
        InputMediaPhoto("AAMCBQADGQEDCmNEaesGnA2IEzOqZHOW0Rq_gLDDEEQAAp4bAAI2XFhXarAfDgUPRYABAAdtAAM7BA"),
        InputMediaPhoto("AAMCBQADGQEDCmNCaesGnI3joyM55Ye_XK13JKnhEdAAAp0bAAI2XFhXOBuF4qvBraYBAAdtAAM7BA"),
        InputMediaPhoto("AAMCBQADGQEDCmNFaesGnMUIsu7Fq3vgwk-kGtA8Gq4AAp8bAAI2XFhXx5RCEgxM-ZIBAAdtAAM7BA"),
        InputMediaPhoto("AAMCBQADGQEDCmNHaesGnDm__uZofB5SJUc9bvL96TkAAqAbAAI2XFhXlfI9-oVRJBcBAAdtAAM7BA"),
    ]
    
    try:
        await update.message.reply_media_group(media)
    except Exception as e:
        await update.message.reply_text("❌ 사진 ID가 옛날 것입니다! 채팅방에 사진을 올려 새 ID를 발급받으세요.")

# 사진을 올리면 ID를 추출해주는 도우미 기능
async def get_photo_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    file_id = update.message.photo[-1].file_id
    await update.message.reply_text(f"{file_id}")

if __name__ == "__main__":
    if TOKEN:
        threading.Thread(target=run_flask, daemon=True).start()
        app = ApplicationBuilder().token(TOKEN).build()
        app.add_handler(CommandHandler("1", event))
        app.add_handler(MessageHandler(filters.PHOTO, get_photo_id))
        app.run_polling()
