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
    seed = random.random() * 100
    if seed < 0.1: return random.randrange(40000, 50001, 500)
    elif seed < 1.1: return random.randrange(30000, 40000, 500)
    elif seed < 4.1: return random.randrange(10000, 30000, 500)
    elif seed < 8.1: return random.randrange(5000, 10000, 500)
    else: return random.randrange(500, 5000, 500)

def build_button_markup(button_data):
    if not button_data: return None
    keyboard = []
    for line in button_data.strip().split('\n'):
        row = [InlineKeyboardButton(btn.split('|')[0].strip(), url=btn.split('|')[1].strip()) 
               for btn in line.split('&&') if '|' in btn]
        if row: keyboard.append(row)
    return InlineKeyboardMarkup(keyboard) if keyboard else None

async def send_custom_output(context, chat_id, data, title=""):
    try:
        photos, caption = data["photos"], f"<b>{title}</b>\n\n{data['caption']}" if title else data['caption']
        markup = build_button_markup(data.get("buttons", ""))
        
        if len(caption) <= 1000:
            if len(photos) == 1:
                await context.bot.send_photo(chat_id, photos[0], caption=caption, parse_mode="HTML", reply_markup=markup)
            else:
                await context.bot.send_media_group(chat_id, [InputMediaPhoto(photos[0], caption=caption, parse_mode="HTML")] + [InputMediaPhoto(fid) for fid in photos[1:]])
                if markup: await context.bot.send_message(chat_id, "⚡️ **아래 버튼을 확인하세요**", reply_markup=markup, parse_mode="HTML")
        else:
            if len(photos) == 1: await context.bot.send_photo(chat_id, photos[0])
            else: await context.bot.send_media_group(chat_id, [InputMediaPhoto(fid) for fid in photos])
            await context.bot.send_message(chat_id, caption, reply_markup=markup, parse_mode="HTML")
    except Exception as e: logging.error(f"전송 실패: {e}")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global db, media_group_cache, message_counter
    if not update.message: return
    
    uid = update.message.from_user.id
    text = update.message.text or ""
    cap = update.message.caption or ""
    is_private = update.effective_chat.type == "private"

    # [1. 주사위] - 그룹/개인 모두 가능
    if text in ["/주사위", "!주사위"]:
        res = get_weighted_dice()
        icon = "💎" if res >= 40000 else "🔥" if res >= 10000 else "🎲"
        name = html.escape(update.message.from_user.first_name)
        return await update.message.reply_text(f"<b>{name}</b>님의 결과: {icon} <b>{res:,}</b>", parse_mode="HTML")

    # [2. 관리자 기능] - 오직 사용자님만 + 오직 1:1 채팅(private)에서만 작동
    if uid == ADMIN_ID and is_private:
        if text == "/카운트확인":
            return await update.message.reply_text(f"📊 현재 누적 카운트: <b>{message_counter}</b>개", parse_mode="HTML")
        
        if text == "/카운트리로드":
            message_counter = 0
            return await update.message.reply_text("🔢 카운트가 초기화되었습니다.")

        if text in ["/리로드", "/삭제", "/리스트"]:
            media_group_cache.clear()
            if not db: return await update.message.reply_text("❌ 등록된 명령어가 없습니다.")
            btns = [[InlineKeyboardButton(f"🗑️ {k}", callback_data=f"del_{k}")] for k in db.keys()]
            return await update.message.reply_text("📋 관리 리스트 (클릭 시 삭제):", reply_markup=InlineKeyboardMarkup(btns))

        # 1:1 채팅에서 사진을 보내면 명령어 등록 시작
        if update.message.photo:
            m_id = update.message.media_group_id or f"s_{update.message.message_id}"
            if m_id not in media_group_cache:
                media_group_cache[m_id] = {"ids": [], "caption": "", "entities": None, "task": None}
            
            media_group_cache[m_id]["ids"].append(update.message.photo[-1].file_id)
            if cap.startswith(("/personal", "/이벤트설정")):
                media_group_cache[m_id]["caption"], media_group_cache[m_id]["entities"] = cap, update.message.caption_entities
            
            if media_group_cache[m_id]["task"]: media_group_cache[m_id]["task"].cancel()
            media_group_cache[m_id]["task"] = asyncio.create_task(save_logic(m_id, update.message.chat_id, context))
            return

    # [3. 카운팅] - 그룹방 대화만 카운트
    if not is_private and not text.startswith(('/', '!')) and not cap.startswith('/'):
        message_counter += 1
        if message_counter > 0 and message_counter % 5000 == 0:
            if "_event_celebration_" in db:
                await send_custom_output(context, update.message.chat_id, db["_event_celebration_"], f"🎊 {message_counter}번째 당첨! 🎊")

    # [4. 명령어 출력] - 등록된 명령어는 어디서든 가능
    if text.startswith(('/', '!')):
        cmd = re.sub(r"^[ /!]+", "", text.split()[0]).strip()
        if cmd in db: await send_custom_output(context, update.message.chat_id, db[cmd])

async def save_logic(m_id, chat_id, context):
    await asyncio.sleep(2.5)
    if m_id in media_group_cache:
        target = media_group_cache[m_id]
        if target["caption"].startswith(("/personal", "/이벤트설정")):
            is_ev = target["caption"].startswith("/이벤트설정")
            parts = target["caption"].split(maxsplit=2)
            key = "_event_celebration_" if is_ev else re.sub(r"^[ /!]+", "", parts[1]).strip()
            content = parts[2] if len(parts) > 2 else (parts[1] if is_ev and len(parts) > 1 else "")
            msg, btn = content, ""
            if "---" in content: msg, btn = content.rsplit("---", 1)
            db[key] = {"photos": target["ids"], "caption": msg.strip(), "buttons": btn.strip()}
            await context.bot.send_message(chat_id, f"✅ {'이벤트' if is_ev else '['+key+']'} 등록 완료! ({len(target['ids'])}장)")
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
