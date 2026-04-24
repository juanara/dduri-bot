from telegram import Update, InputMediaPhoto
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
import os

TOKEN = os.getenv("TOKEN")

async def event(update: Update, context: ContextTypes.DEFAULT_TYPE):
    media = [
        InputMediaPhoto(
            "AAMCBQADGQEDCmM_aesGnHT0ask7yVmTxXnB6Xn1y_kAApobAAI2XFhXpj2CcTONJP4BAAdtAAM7BA",
            caption="""이벤트 문의는 아래 양식으로만 접수합니다.

양식에 맞추지 않고 작성한 문의건은 처리 불가하며, 앞으로 양식 미준수 건은 자동 참여불가 처리합니다.

번거로우시더라도 원활한 처리를 위해 반드시 지켜주시기 바랍니다.

사이트 :
닉네임 :
참여금액 :
이벤트내용 :

※ 첫충/매충 등 동일인이 여러 이벤트를 신청할 경우, 이벤트별로 각각 작성해 주세요.

예)
이벤트1.
사이트 :
닉네임 :
참여금액 :
이벤트내용 :

이벤트2.
사이트 :
닉네임 :
참여금액 :
이벤트내용 :

양식 미준수(예: “이벤트주세요”, “참여요” 등 간단 문의)는 접수 불가합니다.

반복 안내 후에도 양식 미준수 시 향후 이벤트 참여 제한이 있을 수 있으니 협조 부탁드립니다. ☺️

💕사이트 이벤트 = 사이트 고객센터
💕가족방 이벤트 = 연합총장.SITE 💕"""
        ),
        InputMediaPhoto("AAMCBQADGQEDCmNAaesGnIAW3-pmeSScoCJxL432ZMEAApsbAAI2XFhXIGKgBn8d8IgBAAdtAAM7BA"),
        InputMediaPhoto("AAMCBQADGQEDCmNBaesGnKx5XT8a8E8Ga2RUJa7F6qUAApwbAAI2XFhXtyweiMmGAzMBAAdtAAM7BA"),
        InputMediaPhoto("AAMCBQADGQEDCmNEaesGnA2IEzOqZHOW0Rq_gLDDEEQAAp4bAAI2XFhXarAfDgUPRYABAAdtAAM7BA"),
        InputMediaPhoto("AAMCBQADGQEDCmNCaesGnI3joyM55Ye_XK13JKnhEdAAAp0bAAI2XFhXOBuF4qvBraYBAAdtAAM7BA"),
        InputMediaPhoto("AAMCBQADGQEDCmNFaesGnMUIsu7Fq3vgwk-kGtA8Gq4AAp8bAAI2XFhXx5RCEgxM-ZIBAAdtAAM7BA"),
        InputMediaPhoto("AAMCBQADGQEDCmNHaesGnDm__uZofB5SJUc9bvL96TkAAqAbAAI2XFhXlfI9-oVRJBcBAAdtAAM7BA"),
    ]

    await update.message.reply_media_group(media)


app = ApplicationBuilder().token(TOKEN).build()
app.add_handler(CommandHandler("이벤트", event))

print("뜌리봇 실행 중...")
app.run_polling()
