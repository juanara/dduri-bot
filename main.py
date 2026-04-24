import os, re, threading, asyncio, logging, random
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

def parse_premium_emojis(text, entities):
    if not text or not entities: return text or ""
    html_text = list(text)
    for entity in sorted(entities, key=lambda e: e.offset, reverse=True):
        if entity.custom_emoji_id:
            start, end = entity.offset, entity.offset + entity.length
            if start < len(html_text):
                emoji_code = f"<tg-emoji emoji-id='{entity.custom_emoji_id}'>{text[start:end]}</tg-emoji>"
                html_text[start:end] = emoji_code
    return "".join(html_text)

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

def get_weighted_dice():
    rand_val = random.random() * 100
    if rand_val < 90: return 2000
    elif rand_val < 93: return random.randint(10, 50) * 1000
    else:
        return random.choice([1000, 3000, 4000, 5000, 6000, 7000, 8000, 9000])

async def send_custom_output(context, chat_id, data, title=""):
    media = [InputMediaPhoto(data["photos"][0], caption=data["caption"], parse_mode="HTML")]
    media += [InputMediaPhoto(fid) for fid in data["photos"][1:]]
    await context.bot.send_media_group(chat_id=chat_id, media=media)
    markup = build_button_markup(data["buttons"])
    await context.bot.send_message(chat_id=chat_id, text=title or "👇 메뉴 리스트", reply_markup=markup)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global db, media_group_cache, message_counter
    if not update.message: return
    user_id = update.message.from_user.id
    text = update.message.text or ""
    caption = update.message.caption or ""

    # [1. 주사위]
    if text in ["/주사위", "!주사위"]:
        res = get_weighted_dice()
        effect = "🔥" if res >= 10000 else "🎲"
        return await update.message.reply_text(f"{update.message.from_user.first_name}님의 결과: {effect} **{res:,}**", parse_mode="Markdown")

    # [2. 관리자 기능]
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

    # [3. 5,000번 이벤트]
    if not text.startswith(('/', '!')) and not caption.startswith('/'):
        message_counter += 1
        if message_counter > 0 and message_counter % 5000 == 0:
            if "_event_celebration_" in db:
                await send_custom_output(context, update.message.chat_id, db["_event_celebration_"], f"🎊 {message_counter}번째 당첨! 🎊")

    # [4. 명령어 출력]
    if text.startswith(('/', '!')):
        cmd = re.sub(r"^[ /!]+", "", text.split()[0]).strip()
        if cmd in db: await send_custom_output(context, update.message.chat_id, db[cmd])

async def save_logic(m_id, chat_id, context):
    await asyncio.sleep(2.0)
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
            db[cmd_key] = {"photos": target["ids"], "caption": parse_premium_emojis(msg_text.strip(), target["entities"]), "buttons": btn_text.strip()}
            await context.bot.send_message(chat_id=chat_id, text=f"✅ {'이벤트' if is_event else '['+cmd_key+']'} 등록 완료!")
        del media_group_cache[m_id]

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.from_user.id == ADMIN_ID and query.data.startswith("del_"):
        cmd = query.data.replace("del_", "")
        if cmd in db: del db[cmd]
        await query.edit_message_text(f"🗑️ [{cmd}] 삭제 완료.")

if __name__ == "__main__":
    if TOKEN:
        threading.Thread(target=run_flask, daemon=True).start()
        app = ApplicationBuilder().token(TOKEN).build()
        app.add_handler(MessageHandler(filters.ALL, handle_message))
        app.add_handler(CallbackQueryHandler(handle_callback))
        app.run_polling()
