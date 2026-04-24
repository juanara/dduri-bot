import os, re, threading, asyncio, logging, random, html
from telegram import Update, InputMediaPhoto, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes, CallbackQueryHandler
from flask import Flask

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

flask_app = Flask(__name__)
@flask_app.route('/')
def health_check(): return "Bot is running!", 200
def run_flask():
    port = int(os.environ.get("PORT", 10000))
    flask_app.run(host='0.0.0.0', port=port)

TOKEN = os.getenv("TOKEN")
ADMIN_ID = 8472713103 

db = {}
media_group_cache = {}
message_counter = 0

def get_weighted_dice():
    """요청하신 정밀 확률 (500단위)"""
    seed = random.random() * 100
    if seed < 0.1: # 4만이상 (0.1%)
        return random.randrange(40000, 50001, 500)
    elif seed < 1.1: # 3만이상 (1.0%)
        return random.randrange(30000, 40000, 500)
    elif seed < 4.1: # 1만이상 (3.0%)
        return random.randrange(10000, 30000, 500)
    elif seed < 8.1: # 5천이상 (4.0%)
        return random.randrange(5000, 10000, 500)
    else: # 5천미만 나머지
        return random.randrange(500, 5000, 500)

def build_button_markup(button_data):
    keyboard = []
    if not button_data: return None
    lines = button_data.strip().split('\n')
    for line in lines:
        row = []
        buttons = line.split('&&')
        for btn in buttons:
            if '|' in btn:
                name, url = btn.split('|', 1)
                row.append(InlineKeyboardButton(name.strip(), url=url.strip()))
        if row: keyboard.append(row)
    return InlineKeyboardMarkup(keyboard)

async def send_custom_output(context, chat_id, data, title=""):
    """사진 캡션으로 글을 넣는 통합 전송 방식"""
    try:
        photos = data["photos"]
        # 제목이 있으면 본문 위에 합침
        full_caption = f"<b>{title}</b>\n\n{data['caption']}" if title else data['caption']
        markup = build_button_markup(data.get("buttons", ""))

        if len(photos) == 1:
            # 사진 1장: 사진+글+버튼이 완벽하게 한 세트로 나감
            await context.bot.send_photo(
                chat_id=chat_id, 
                photo=photos[0], 
                caption=full_caption, 
                parse_mode="HTML", 
                reply_markup=markup
            )
        else:
            # 사진 여러 장: 첫 번째 사진에 글을 붙이고, 버튼은 바로 아래 메시지로 전송
            media = [InputMediaPhoto(photos[0], caption=full_caption, parse_mode="HTML")]
            media += [InputMediaPhoto(fid) for fid in photos[1:]]
            await context.bot.send_media_group(chat_id=chat_id, media=media)
            if markup:
                await context.bot.send_message(chat_id=chat_id, text="👇 하단 메뉴를 이용하세요.", reply_markup=markup)
    except Exception as e:
        logging.error(f"전송 오류 (글자 수 초과 가능성): {e}")
        # 오류 발생 시 안전하게 텍스트만이라도 전송
        await context.bot.send_message(chat_id=chat_id, text=f"⚠️ 전송 오류(내용이 너무 길 수 있습니다):\n\n{full_caption[:1000]}", parse_mode="HTML")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global db, media_group_cache, message_counter
    if not update.message: return
    user_id = update.message.from_user.id
    text = update.message.text or ""
    caption = update.message.caption or ""

    # [주사위]
    if text in ["/주사위", "!주사위"]:
        res = get_weighted_dice()
        user_name = html.escape(update.message.from_user.first_name)
        icon = "💎" if res >= 40000 else "🔥" if res >= 10000 else "🎲"
        return await update.message.reply_text(f"<b>{user_name}</b>님의 결과: {icon} <b>{res:,}</b>", parse_mode="HTML")

    # [관리자 전용]
    if user_id == ADMIN_ID:
        if text == "/카운트확인": return await update.message.reply_text(f"📊 카운트: {message_counter}")
        if text == "/카운트리로드":
            message_counter = 0
            return await update.message.reply_text("🔢 초기화 완료")
        
        if update.message.photo:
            m_id = update.message.media_group_id or f"s_{update.message.message_id}"
            if m_id not in media_group_cache:
                media_group_cache[m_id] = {"ids": [], "caption": "", "entities": None, "task": None}
            media_group_cache[m_id]["ids"].append(update.message.photo[-1].file_id)
            if caption.startswith(("/personal", "/이벤트설정")):
                media_group_cache[m_id]["caption"] = caption
                media_group_cache[m_id]["entities"] = update.message.caption_entities
            if media_group_cache[m_id]["task"]: media_group_cache[m_id]["task"].cancel()
            media_group_cache[m_id]["task"] = asyncio.create_task(save_logic(m_id, update.message.chat_id, context))
            return

    # [5,000번 이벤트 카운트]
    if not text.startswith(('/', '!')) and not caption.startswith('/'):
        message_counter += 1
        if message_counter > 0 and message_counter % 5000 == 0:
            if "_event_celebration_" in db:
                await send_custom_output(context, update.message.chat_id, db["_event_celebration_"], f"🎊 {message_counter}번째 당첨! 🎊")

    # [명령어 출력]
    if text.startswith(('/', '!')):
        cmd = re.sub(r"^[ /!]+", "", text.split()[0]).strip()
        if cmd in db:
            await send_custom_output(context, update.message.chat_id, db[cmd])

async def save_logic(m_id, chat_id, context):
    await asyncio.sleep(2.5)
    if m_id in media_group_cache:
        target = media_group_cache[m_id]
        cap = target["caption"]
        if cap.startswith(("/personal", "/이벤트설정")):
            is_event = cap.startswith("/이벤트설정")
            parts = cap.split(maxsplit=2)
            cmd_key = "_event_celebration_" if is_event else re.sub(r"^[ /!]+", "", parts[1]).strip()
            content = parts[2] if len(parts) > 2 else (parts[1] if is_event and len(parts) > 1 else "")
            msg_text, btn_text = content, ""
            if "---" in content: msg_text, btn_text = content.rsplit("---", 1)
            db[cmd_key] = {"photos": target["ids"], "caption": msg_text.strip(), "buttons": btn_text.strip()}
            await context.bot.send_message(chat_id=chat_id, text=f"✅ 등록 완료! (사진 {len(target['ids'])}장)")
        del media_group_cache[m_id]

if __name__ == "__main__":
    if TOKEN:
        threading.Thread(target=run_flask, daemon=True).start()
        app = ApplicationBuilder().token(TOKEN).build()
        app.add_handler(MessageHandler(filters.ALL, handle_message))
        app.run_polling()
