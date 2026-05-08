import os, re, threading, asyncio, logging, random, html
from datetime import datetime, timedelta, timezone
from telegram import Update, InputMediaPhoto, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes, CallbackQueryHandler
from flask import Flask
from pymongo import MongoClient
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.types import User
from bson.objectid import ObjectId

# 1. 로그 및 환경 설정
logging.basicConfig(level=logging.INFO)
KST = timezone(timedelta(hours=9))

TOKEN = os.getenv("TOKEN")
API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH")
STRING_SESSION = os.getenv("STRING_SESSION")
MONGO_URL = os.getenv("MONGO_URL")

# 본계정, 부계정 ID (쉼표 구분)
ADMIN_ID_STR = os.getenv("ADMIN_ID", "8092185425")
ADMIN_LIST = [int(i.strip()) for i in ADMIN_ID_STR.split(",") if i.strip()]

client = MongoClient(MONGO_URL)
mongodb = client['dduri3_bot_db']
col_main, col_members, col_sched, col_sessions = mongodb['settings'], mongodb['members'], mongodb['schedules'], mongodb['admin_sessions']

userbot = TelegramClient(StringSession(STRING_SESSION), API_ID, API_HASH)
media_group_cache = {}
last_run_cache = {}

# [해결 1] balance_html에서 tg-emoji 제거하여 엔티티 파손 방지
def balance_html(text):
    if not text: return ""
    tags = ['b', 'i', 'u', 's', 'code', 'pre', 'blockquote']
    for tag in tags:
        opened = len(re.findall(f'<{tag}[^>]*>', text))
        closed = len(re.findall(f'</{tag}>', text))
        if opened > closed: text += f'</{tag}>' * (opened - closed)
        if closed > opened: text = f'<{tag}>' * (closed - opened) + text
    return text

async def check_auth(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid in ADMIN_LIST: return True
    try:
        member = await context.bot.get_chat_member(update.effective_chat.id, uid)
        return member.status in ["administrator", "creator"]
    except: return False

async def sync_members(chat_id):
    try:
        new_users = {}
        async for u in userbot.iter_participants(chat_id):
            if isinstance(u, User) and not u.bot and not u.deleted:
                new_users[str(u.id)] = html.escape(u.first_name)
        col_members.update_one({"chat_id": str(chat_id)}, {"$set": {"users": new_users, "room_name": "이름 동기화 필요"}}, upsert=True)
        return len(new_users)
    except: return 0

async def send_custom_output(bot, chat_id, data, title=""):
    try:
        photos, caption, cid = data.get("photos", []), (f"<b>{title}</b>\n\n{data['caption']}" if title else data['caption']), str(chat_id)
        markup = None
        if data.get("buttons"):
            btn_lines = []
            for line in data["buttons"].split('\n'):
                row = [InlineKeyboardButton(b.split('|')[0].strip(), url=b.split('|')[1].strip()) for b in line.split('&&') if '|' in b]
                if row: btn_lines.append(row)
            if btn_lines: markup = InlineKeyboardMarkup(btn_lines)
            
        if not photos: 
            await bot.send_message(cid, caption, parse_mode="HTML", reply_markup=markup)
        elif len(photos) == 1: 
            await bot.send_photo(cid, photos[0], caption=caption, parse_mode="HTML", reply_markup=markup)
        else:
            media = [InputMediaPhoto(photos[0], caption=caption, parse_mode="HTML")] + [InputMediaPhoto(f) for f in photos[1:]]
            await bot.send_media_group(cid, media)
            if markup: await bot.send_message(cid, "⚡️ 버튼 확인", reply_markup=markup)
    except Exception as e:
        logging.error(f"Send Error: {e}")

async def custom_scheduler_loop(application):
    await asyncio.sleep(15)
    bot = application.bot
    while True:
        try:
            now = datetime.now(KST)
            now_str, curr_t = now.strftime("%Y-%m-%d %H:%M"), now.strftime("%H%M")
            for s in list(col_sched.find()):
                sid = str(s['_id'])
                if not (s['start_dt'] <= now_str <= s['end_dt']):
                    if now_str > s['end_dt']: col_sched.delete_one({"_id": s['_id']})
                    continue
                if not (s['slot_start'] <= curr_t <= s['slot_end']): continue
                last_run = last_run_cache.get(sid)
                if not last_run or (now - last_run).total_seconds() >= s['interval'] * 60:
                    last_run_cache[sid] = now
                    await send_custom_output(bot, s['chat_id'], s['data'])
        except: pass
        await asyncio.sleep(30)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message: return
    uid, chat_id = update.effective_user.id, update.effective_chat.id
    text = update.message.text or ""
    
    if await check_auth(update, context):
        if text == "/동기화":
            msg = await update.message.reply_text("🔄 명단 갱신 중...")
            count = await sync_members(chat_id)
            col_members.update_one({"chat_id": str(chat_id)}, {"$set": {"room_name": update.effective_chat.title}}, upsert=True)
            await msg.edit_text(f"✅ 완료! {count}명 확보.")
            return
        if text.lower().startswith("/all"):
            room = col_members.find_one({"chat_id": str(chat_id)})
            m_list = list(room.get("users", {}).items()) if room else []
            for i in range(0, len(m_list), 10):
                mentions = [f"<a href='tg://user?id={mid}'>{name}</a>" for mid, name in m_list[i:i+10]]
                await context.bot.send_message(chat_id, " ".join(mentions), parse_mode="HTML")
                await asyncio.sleep(0.5)
            return

    if uid in ADMIN_LIST and update.effective_chat.type == "private":
        if text.startswith(('/설정', '/리스트', '/삭제')):
            btns = [[InlineKeyboardButton("📁 [공용] 설정", callback_data="set_room:common")]]
            for r in list(col_members.find()):
                if "room_name" in r: btns.append([InlineKeyboardButton(f"🏠 {r['room_name']}", callback_data=f"set_room:{r['chat_id']}")])
            return await update.message.reply_text("📂 관리할 방 선택:", reply_markup=InlineKeyboardMarkup(btns))
        
        # [해결 2] _urled 속성 제거 및 caption_html 원본 사용
        raw_html = update.message.caption_html or update.message.text_html or ""
        
        if update.message.photo or "/타이머" in text or "/명령어등록" in text:
            m_id = update.message.media_group_id or f"s_{update.message.message_id}"
            if update.message.photo:
                if m_id not in media_group_cache: media_group_cache[m_id] = {"ids": [], "caption": raw_html, "task": None}
                media_group_cache[m_id]["ids"].append(update.message.photo[-1].file_id)
                if media_group_cache[m_id]["task"]: media_group_cache[m_id]["task"].cancel()
                media_group_cache[m_id]["task"] = asyncio.create_task(save_logic(chat_id, context, m_id, None, uid))
            else: await save_logic(chat_id, context, None, update.message, uid)
            return

    if text.startswith(('/', '!')):
        cmd = re.sub(r"^[ /!]+", "", text.split()[0]).strip()
        room = col_members.find_one({"chat_id": str(chat_id)})
        target = (room.get("local_commands", {}).get(cmd) if room else None) or col_main.find_one({"id": "bot_main_data"}).get("commands", {}).get(cmd)
        if target: await send_custom_output(context.bot, chat_id, target)

async def save_logic(chat_id, context, m_id, message, uid):
    if m_id: await asyncio.sleep(3.5)
    # [해결 3] save_logic 내에서도 _urled 제거
    raw_html = media_group_cache[m_id]["caption"] if m_id else (message.caption_html or message.text_html or "")
    sess = col_sessions.find_one({"admin_id": uid}); t_id = sess['target_chat_id'] if sess else None
    if not t_id: return await context.bot.send_message(chat_id, "⚠️ 방 선택 먼저 하세요.")
    
    try:
        if "/타이머" in raw_html:
            m = re.search(r"/타이머\s+([^-]+)-(\d{12})-(\d{12})-(\d+)\s*(.*)", raw_html, re.IGNORECASE | re.DOTALL)
            if m:
                name, s_raw, e_raw, intv, content = m.groups()
                data = {"chat_id": t_id, "name": name.strip(), "start_dt": f"{s_raw[:4]}-{s_raw[4:6]}-{s_raw[6:8]} {s_raw[8:10]}:{s_raw[10:12]}", "end_dt": f"{e_raw[:4]}-{e_raw[4:6]}-{e_raw[6:8]} {e_raw[8:10]}:{e_raw[10:12]}", "slot_start": s_raw[8:12], "slot_end": e_raw[8:12], "interval": int(intv), "data": {"photos": (media_group_cache[m_id]["ids"] if m_id else []), "caption": balance_html(content.strip())}}
                col_sched.insert_one(data); await context.bot.send_message(chat_id, "⏰ 타이머 완료!")
        elif "/명령어등록" in raw_html:
            m = re.search(r"/명령어등록\s+([^<\s]+)\s*(.*)", raw_html, re.IGNORECASE | re.DOTALL)
            if m:
                key, content = m.groups()
                msg, btn = content.rsplit("---", 1) if "---" in content else (content, "")
                cmd_data = {"photos": (media_group_cache[m_id]["ids"] if m_id else []), "caption": balance_html(msg.strip()), "buttons": re.sub('<[^<]+?>', '', btn).strip()}
                if t_id == "common": col_main.update_one({"id": "bot_main_data"}, {"$set": {f"commands.{key}": cmd_data}}, upsert=True)
                else: col_members.update_one({"chat_id": t_id}, {"$set": {f"local_commands.{key}": cmd_data}}, upsert=True)
                await context.bot.send_message(chat_id, f"✅ [{key}] 저장 완료!")
    except Exception as e: await context.bot.send_message(chat_id, f"❌ 에러: {e}")
    if m_id in media_group_cache: del media_group_cache[m_id]

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; data = query.data; uid = query.from_user.id
    if uid not in ADMIN_LIST: return
    if data.startswith("set_room:"):
        r_id = data.split(":")[1]; col_sessions.update_one({"admin_id": uid}, {"$set": {"target_chat_id": r_id}}, upsert=True)
        btns = [[InlineKeyboardButton("📋 리스트", callback_data=f"show_list:{r_id}"), InlineKeyboardButton("⏰ 타이머", callback_data=f"show_sched:{r_id}")]]
        await query.edit_message_text(f"🎯 활성화됨", reply_markup=InlineKeyboardMarkup(btns))
    elif data.startswith("show_list:"):
        r_id = data.split(":")[1]
        target = col_main.find_one({"id": "bot_main_data"}).get("commands", {}) if r_id == "common" else (col_members.find_one({"chat_id": r_id}).get("local_commands", {}) if col_members.find_one({"chat_id": r_id}) else {})
        btns = [[InlineKeyboardButton(f"🗑 {k}", callback_data=f"del:{r_id}:{k}")] for k in target.keys()]; btns.append([InlineKeyboardButton("🔙", callback_data="back_to_rooms")])
        await query.edit_message_text("🗑 삭제 선택:", reply_markup=InlineKeyboardMarkup(btns))
    elif data.startswith("del:"):
        _, r_id, k = data.split(":", 2)
        if r_id == "common": col_main.update_one({"id": "bot_main_data"}, {"$unset": {f"commands.{k}": ""}})
        else: col_members.update_one({"chat_id": r_id}, {"$unset": {f"local_commands.{k}": ""}})
        await query.answer("삭제!"); await handle_callback(update, context)
    elif data == "back_to_rooms":
        btns = [[InlineKeyboardButton("📁 [공용]", callback_data="set_room:common")]] + [[InlineKeyboardButton(f"🏠 {r['room_name']}", callback_data=f"set_room:{r['chat_id']}") ] for r in list(col_members.find()) if "room_name" in r]
        await query.edit_message_text("📂 방 선택:", reply_markup=InlineKeyboardMarkup(btns))

flask_app = Flask(__name__)
@flask_app.route('/')
def home(): return "OK", 200

async def post_init(application):
    await userbot.start()
    asyncio.create_task(custom_scheduler_loop(application))

if __name__ == "__main__":
    threading.Thread(target=lambda: flask_app.run(host='0.0.0.0', port=10000), daemon=True).start()
    app = ApplicationBuilder().token(TOKEN).post_init(post_init).build()
    app.add_handler(MessageHandler(filters.ALL, handle_message)); app.add_handler(CallbackQueryHandler(handle_callback))
    app.run_polling()
