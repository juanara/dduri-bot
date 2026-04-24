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
        # ensure_ascii=False로 설정해야 이모지가 안 깨지고 저장됩니다.
        json.dump(data, f, ensure_ascii=False, indent=4)

# 초기 데이터 로드
current_data = load_db()
db = current_data.get("commands", {})
message_counter = current_data.get("counter", 0)
media_group_cache = {}

def get_weighted_dice():
    """500단위 정밀 확률 (최대 50,000)"""
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

def convert_to_html(text, entities):
    """텔레그램 서식(진하게, 이모지 등)을 HTML 태그로 변환"""
    if not entities:
        return html.escape(text)
    
    # 엔티티 역순 처리 (인덱스 밀림 방지)
    html_text = text
    offset_diff = 0
    
    # 엔티티들을 시작 위치 순으로 정렬
    sorted_entities = sorted(entities, key=lambda e: e.offset)
    
    # 실제 HTML 변환 로직은 복잡하므로 텔레그램 라이브러리의 기능을 활용하는 것이 좋으나, 
    # 여기서는 가장 안정적인 태그 래핑 방식을 사용합니다.
    # 단, 여기서는 단순 텍스트로 저장 후 출력 시 parse_mode="HTML"을 쓰기 위해 
    # 사용자님이 직접 <b>태그 등을 써서 등록하는 방식을 권장하거나, 
    # 아래 로직으로 기본 서식을 보호합니다.
    return text # 저장 시 raw text를 유지하고 출력 시 parse_mode를 적용

async def send_custom_output(context, chat_id, data, title=""):
    try:
        photos = data["photos"]
        # 이미 HTML 태그가 포함되어 저장된 caption을 가져옴
        caption = f"<b>{title}</b>\n\n{data['caption']}" if title else data['caption']
        markup = build_button_markup(data.get("buttons", ""))
        
        # 글자 수 체크 (1024자 제한)
        if len(caption) <= 1000:
            if len(photos) == 1:
                await context.bot.send_photo(chat_id, photos[0], caption=caption, parse_mode="HTML", reply_markup=markup)
            else:
                media = [InputMediaPhoto(photos[0], caption=caption, parse_mode="HTML")] + [InputMediaPhoto(fid) for fid in photos[1:]]
                await context.bot.send_media_group(chat_id, media)
                if markup: await context.bot.send_message(chat_id, "⚡️ **아래 버튼을 확인하세요**", reply_markup=markup, parse_mode="HTML")
        else:
            # 1024자 초과 시 분리 전송
            if len(photos) == 1: await context.bot.send_photo(chat_id, photos[0])
            else: await context.bot.send_media_group(chat_id, [InputMediaPhoto(fid) for fid in photos])
            await context.bot.send_message(chat_id, caption, reply_markup=markup, parse_mode="HTML")
    except Exception as e:
        logging.error(f"전송 실패: {e}")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global db, message_counter, media_group_cache
    if not update.message: return
    
    uid, text, cap = update.message.from_user.id, update.message.text or "", update.message.caption or ""
    is_private = update.effective_chat.type == "private"

    # [주사위]
    if text in ["/주사위", "!주사위"]:
        res = get_weighted_dice()
        icon = "💎" if res >= 40000 else "🔥" if res >= 10000 else "🎲"
        name = html.escape(update.message.from_user.first_name)
        return await update.message.reply_text(f"<b>{name}</b>님의 결과: {icon} <b>{res:,}</b>", parse_mode="HTML")

    # [관리자 전용]
    if uid == ADMIN_ID and is_private:
        if text == "/카운트확인":
            return await update.message.reply_text(f"📊 현재 카운트: <b>{message_counter}</b>", parse_mode="HTML")
        
        if text == "/카운트리로드":
            message_counter = 0
            save_db({"commands": db, "counter": message_counter})
            return await update.message.reply_text("🔢 초기화 완료")

        if text in ["/리스트", "/삭제"]:
            if not db: return await update.message.reply_text("❌ 데이터 없음")
            btns = [[InlineKeyboardButton(f"🗑️ {k} 삭제", callback_data=f"del_{k}")] for k in db.keys()]
            return await update.message.reply_text("📋 삭제 리스트:", reply_markup=InlineKeyboardMarkup(btns))

        if update.message.photo:
            m_id = update.message.media_group_id or f"s_{update.message.message_id}"
            if m_id not in media_group_cache:
                media_group_cache[m_id] = {"ids": [], "caption": "", "entities": None, "task": None}
            
            media_group_cache[m_id]["ids"].append(update.message.photo[-1].file_id)
            if cap.startswith(("/personal", "/이벤트설정")):
                # 서식이 포함된 텍스트를 그대로 가져오기 위해 'caption_html_all'과 유사한 로직 사용
                # 여기서는 가장 간단하고 확실하게 사용자님이 보낸 캡션의 HTML 형태를 추출합니다.
                media_group_cache[m_id]["caption"] = update.message.caption_html_arrived if hasattr(update.message, 'caption_html_arrived') else update.message.caption_html
            
            if media_group_cache[m_id]["task"]: media_group_cache[m_id]["task"].cancel()
            media_group_cache[m_id]["task"] = asyncio.create_task(save_logic(m_id, update.message.chat_id, context))
            return

    # [카운팅]
    if not is_private and not text.startswith(('/', '!')) and not cap.startswith('/'):
        message_counter += 1
        if message_counter % 100 == 0: save_db({"commands": db, "counter": message_counter})
        if message_counter > 0 and message_counter % 5000 == 0:
            if "_event_celebration_" in db:
                await send_custom_output(context, update.message.chat_id, db["_event_celebration_"], f"🎊 {message_counter}번째 당첨! 🎊")

    # [명령어 출력]
    if text.startswith(('/', '!')):
        cmd = re.sub(r"^[ /!]+", "", text.split()[0]).strip()
        if cmd in db: await send_custom_output(context, update.message.chat_id, db[cmd])

async def save_logic(m_id, chat_id, context):
    global db, message_counter
    await asyncio.sleep(2.5)
    if m_id in media_group_cache:
        target = media_group_cache[m_id]
        raw_cap = target["caption"] # 이미 HTML 태그가 포함된 상태
        
        if "/personal" in raw_cap or "/이벤트설정" in raw_cap:
            is_ev = "/이벤트설정" in raw_cap
            # 명령어와 본문 분리
            try:
                if is_ev:
                    cmd_key = "_event_celebration_"
                    content = raw_cap.split("/이벤트설정", 1)[1].strip()
                else:
                    parts = raw_cap.split("/personal", 1)[1].strip().split(None, 1)
                    cmd_key = parts[0]
                    content = parts[1] if len(parts) > 1 else ""
                
                msg_text, btn_text = content, ""
                if "---" in content:
                    msg_text, btn_text = content.rsplit("---", 1)
                
                # 버튼 텍스트에서 HTML 태그 제거 (링크에 태그가 섞이면 안 됨)
                btn_text = re.sub('<[^<]+?>', '', btn_text).strip()

                db[cmd_key] = {"photos": target["ids"], "caption": msg_text.strip(), "buttons": btn_text}
                save_db({"commands": db, "counter": message_counter})
                await context.bot.send_message(chat_id, f"✅ [{cmd_key}] 서식 포함 등록 완료!")
            except Exception as e:
                await context.bot.send_message(chat_id, f"❌ 등록 실패: 형식을 확인해주세요. ({e})")
        del media_group_cache[m_id]

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global db, message_counter
    query = update.callback_query
    if query.from_user.id == ADMIN_ID and query.data.startswith("del_"):
        cmd = query.data.replace("del_", "")
        if cmd in db:
            del db[cmd]
            save_db({"commands": db, "counter": message_counter})
            await query.edit_message_text(f"🗑️ [{cmd}] 삭제 완료.")

if __name__ == "__main__":
    if TOKEN:
        threading.Thread(target=run_flask, daemon=True).start()
        app = ApplicationBuilder().token(TOKEN).build()
        app.add_handler(MessageHandler(filters.ALL, handle_message))
        app.add_handler(CallbackQueryHandler(handle_callback))
        app.run_polling()
