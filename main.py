import os, re, threading, asyncio, logging, random, html, json
from telegram import Update, InputMediaPhoto, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes, CallbackQueryHandler
from flask import Flask

# 로그 설정
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

flask_app = Flask(__name__)
@flask_app.route('/')
def health_check(): return "Bot is running!", 200
def run_flask():
    port = int(os.environ.get("PORT", 10000))
    flask_app.run(host='0.0.0.0', port=port)

TOKEN = os.getenv("TOKEN")
ADMIN_ID = 8472713103 

# [데이터 영구 저장 로직]
DB_FILE = "database.json"

def load_db():
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except: pass
    return {"commands": {}, "counter": 0}

def save_db(data):
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

# 초기 데이터 로드
current_data = load_db()
db = current_data["commands"]
message_counter = current_data["counter"]
media_group_cache = {}

def get_weighted_dice():
    seed = random.random() * 100
    if seed < 0.01: return random.randrange(40000, 50001, 500)
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
        
        # 글자 수에 따른 자동 분리 전송
        if len(caption) <= 1000:
            if len(photos) == 1:
                await context.bot.send_photo(chat_id, photos[0], caption=caption, parse_mode="HTML", reply_markup=markup)
            else:
                media = [InputMediaPhoto(photos[0], caption=caption, parse_mode="HTML")] + [InputMediaPhoto(fid) for fid in photos[1:]]
                await context.bot.send_media_group(chat_id, media)
                if markup: await context.bot.send_message(chat_id, "⚡️ **버튼을 확인하세요**", reply_markup=markup, parse_mode="HTML")
        else:
            if len(photos) == 1: await context.bot.send_photo(chat_id, photos[0])
            else: await context.bot.send_media_group(chat_id, [InputMediaPhoto(fid) for fid in photos])
            await context.bot.send_message(chat_id, caption, reply_markup=markup, parse_mode="HTML")
    except Exception as e: logging.error(f"Output Error: {e}")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global db, message_counter, media_group_cache
    if not update.message: return
    
    uid, text, cap = update.message.from_user.id, update.message.text or "", update.message.caption or ""
    is_private = update.effective_chat.type == "private"

    # [1. 주사위]
    if text in ["/주사위", "!주사위"]:
        res = get_weighted_dice()
        icon = "💎" if res >= 40000 else "🔥" if res >= 10000 else "🎲"
        name = html.escape(update.message.from_user.first_name)
        return await update.message.reply_text(f"<b>{name}</b>님의 결과: {icon} <b>{res:,}</b>", parse_mode="HTML")

    # [2. 관리자 기능 - 오직 뜌리봇과 1:1에서만]
    if uid == ADMIN_ID and is_private:
        if text == "/카운트확인":
            return await update.message.reply_text(f"📊 현재 카운트: <b>{message_counter}</b>", parse_mode="HTML")
        
        if text == "/카운트리로드":
            message_counter = 0
            save_db({"commands": db, "counter": message_counter})
            return await update.message.reply_text("🔢 카운트 초기화 완료")

        if text in ["/리스트", "/삭제", "/명령어관리"]:
            if not db: return await update.message.reply_text("❌ 등록된 명령어가 없습니다.")
            btns = [[InlineKeyboardButton(f"🗑️ {k} 삭제", callback_data=f"del_{k}")] for k in db.keys() if k != "_event_celebration_"]
            if "_event_celebration_" in db:
                btns.append([InlineKeyboardButton("🗑️ 당첨이벤트 문구 삭제", callback_data="del__event_celebration_")])
            return await update.message.reply_text("📋 삭제할 명령어를 선택하세요:", reply_markup=InlineKeyboardMarkup(btns))

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

    # [3. 카운팅 - 그룹방에서만]
    if not is_private and not text.startswith(('/', '!')) and not cap.startswith('/'):
        message_counter += 1
        # 100개마다 자동 저장 (서버 재시작 대비)
        if message_counter % 100 == 0: save_db({"commands": db, "counter": message_counter})
        
        if message_counter > 0 and message_counter % 5000 == 0:
            if "_event_celebration_" in db:
                await send_custom_output(context, update.message.chat_id, db["_event_celebration_"], f"🎊 {message_counter}번째 당첨! 🎊")

    # [4. 명령어 출력]
    if text.startswith(('/', '!')):
        cmd = re.sub(r"^[ /!]+", "", text.split()[0]).strip()
        if cmd in db: await send_custom_output(context, update.message.chat_id, db[cmd])

async def save_logic(m_id, chat_id, context):
    global db, message_counter
    await asyncio.sleep(2.5)
    if m_id in media_group_cache:
        target = media_group_cache[m_id]
        cap = target["caption"]
        if cap.startswith(("/personal", "/이벤트설정")):
            is_ev = cap.startswith("/이벤트설정")
            parts = cap.split(maxsplit=2)
            key = "_event_celebration_" if is_ev else re.sub(r"^[ /!]+", "", parts[1]).strip()
            content = parts[2] if len(parts) > 2 else (parts[1] if is_ev and len(parts) > 1 else "")
            msg, btn = content, ""
            if "---" in content: msg, btn = content.rsplit("---", 1)
            
            db[key] = {"photos": target["ids"], "caption": msg.strip(), "buttons": btn.strip()}
            save_db({"commands": db, "counter": message_counter}) # 파일에 저장
            await context.bot.send_message(chat_id, f"✅ {'당첨 이벤트' if is_ev else '['+key+']'} 등록 완료!")
        del media_group_cache[m_id]

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global db, message_counter
    query = update.callback_query
    if query.from_user.id == ADMIN_ID and query.data.startswith("del_"):
        cmd = query.data.replace("del_", "")
        if cmd in db:
            del db[cmd]
            save_db({"commands": db, "counter": message_counter}) # 파일에서도 삭제
            await query.answer("삭제 완료!")
            await query.edit_message_text(f"🗑️ [{cmd}] 명령어가 완전히 삭제되었습니다.")
        else:
            await query.answer("이미 삭제된 명령어입니다.")

if __name__ == "__main__":
    if TOKEN:
        threading.Thread(target=run_flask, daemon=True).start()
        app = ApplicationBuilder().token(TOKEN).build()
        app.add_handler(MessageHandler(filters.ALL, handle_message))
        app.add_handler(CallbackQueryHandler(handle_callback))
        app.run_polling()
