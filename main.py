import os, re, threading, asyncio, logging, html, json, requests
from datetime import datetime, timedelta, timezone
from telegram import Update, InputMediaPhoto, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes, CallbackQueryHandler
from flask import Flask
from pymongo import MongoClient
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.types import User
from bson.objectid import ObjectId

# 1. 시스템 설정 및 로깅
logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)
KST = timezone(timedelta(hours=9))

# 2. 환경 변수 및 DB 연결
TOKEN = os.getenv("TOKEN")
API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH")
STRING_SESSION = os.getenv("STRING_SESSION")
MONGO_URL = os.getenv("MONGO_URL")

# 멀티 관리자 리스트
ADMIN_ID_STR = os.getenv("ADMIN_ID", "8472713103,8092185425")
ADMIN_LIST = [int(i.strip()) for i in ADMIN_ID_STR.split(",") if i.strip()]

client = MongoClient(MONGO_URL)
mongodb = client['dduri_bot_db']
col_main, col_members, col_sched, col_sessions = mongodb['settings'], mongodb['members'], mongodb['schedules'], mongodb['admin_sessions']

# 텔레톤 유저봇 및 캐시
userbot = TelegramClient(StringSession(STRING_SESSION), API_ID, API_HASH)
media_group_cache = {}

# 엔진 html 태그 밸런서
def balance_html(text):
    if not text: return ""
    tags = ['b', 'i', 'u', 's', 'code', 'pre', 'blockquote']
    for tag in tags:
        opened = len(re.findall(f'<{tag}[^>]*>', text))
        closed = len(re.findall(f'</{tag}>', text))
        if opened > closed: text += f'</{tag}>' * (opened - closed)
        if closed > opened: text = f'<{tag}>' * (closed - opened) + text
    return text

def clean_tags(t):
    return re.sub(r'<[^>]+>', '', str(t)).strip()

async def check_auth(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid in ADMIN_LIST: return True
    if update.effective_chat.type == "private": return False
    try:
        member = await context.bot.get_chat_member(update.effective_chat.id, uid)
        return member.status in ["administrator", "creator"]
    except: return False

async def send_custom_output(bot, chat_id, data, title=""):
    try:
        c_str = str(chat_id).strip()
        cid = int(c_str) if (c_str.isdigit() or (c_str.startswith('-') and c_str[1:].isdigit())) else c_str
        
        photos = data.get("photos", [])
        caption = f"<b>{title}</b>\n\n{data['caption']}" if title else data['caption']
        markup = None
        
        if data.get("buttons"):
            btns = [[InlineKeyboardButton(b.split('|')[0].strip(), url=b.split('|')[1].strip()) for b in line.split('&&') if '|' in b] for line in data["buttons"].split('\n')]
            if btns[0]: markup = InlineKeyboardMarkup(btns)
            
        if not photos: await bot.send_message(cid, caption, parse_mode="HTML", reply_markup=markup)
        elif len(photos) == 1: await bot.send_photo(cid, photos[0], caption=caption, parse_mode="HTML", reply_markup=markup)
        else:
            media = [InputMediaPhoto(photos[0], caption=caption, parse_mode="HTML")] + [InputMediaPhoto(f) for f in photos[1:]]
            await bot.send_media_group(cid, media)
            if markup: await bot.send_message(cid, "⚡️ 버튼 확인", reply_markup=markup)
    except Exception as e:
        logging.error(f"최종 출력 엔진 오류 발생 {e}")

async def custom_scheduler_loop(application):
    await asyncio.sleep(10)
    bot = application.bot
    while True:
        try:
            now = datetime.now(KST)
            now_date, now_time = now.strftime("%Y%m%d"), now.strftime("%H%M")
            
            for s in list(col_sched.find()):
                sid = str(s['_id'])
                if not (s['start_dt'] <= now_date <= s['end_dt']):
                    if now_date > s['end_dt']: col_sched.delete_one({"_id": s['_id']})
                    continue
                if not (s['slot_start'] <= now_time <= s['slot_end']): continue
                
                # 디비에서 타임스탬프 로드
                last_run_ts = s.get('last_run_ts')
                
                # 새 스케줄 등록 즉시 실행 방지
                if last_run_ts is None:
                    col_sched.update_one({"_id": s['_id']}, {"$set": {"last_run_ts": now.timestamp()}})
                    continue
                    
                if now.timestamp() - last_run_ts >= s['interval'] * 60:
                    col_sched.update_one({"_id": s['_id']}, {"$set": {"last_run_ts": now.timestamp()}})
                    if s['chat_id'] == "common":
                        for r in list(col_members.find()): await send_custom_output(bot, r['chat_id'], s['data'])
                    else: await send_custom_output(bot, s['chat_id'], s['data'])
        except Exception as loop_err:
            logging.error(f"스케줄러 루프 예외 발생 {loop_err}")
        await asyncio.sleep(20)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message: return
    uid, chat_id = update.effective_user.id, update.effective_chat.id
    text = (update.message.text or "").strip()
    
    if await check_auth(update, context):
        if text == "/동기화":
            msg = await update.message.reply_text("🔄 DB 최신화 중")
            users = {str(u.id): html.escape(u.first_name) async for u in userbot.iter_participants(chat_id) if isinstance(u, User) and not u.bot and not u.deleted}
            col_members.update_one({"chat_id": str(chat_id)}, {"$set": {"room_name": update.effective_chat.title, "users": users}}, upsert=True)
            await msg.edit_text(f"✅ 동기화 완료 인원 {len(users)}명")
            return
        if text.startswith(("/all", "/전체공지")):
            room = col_members.find_one({"chat_id": str(chat_id)})
            m_list = list(room.get("users", {}).items()) if room else []
            if not m_list: return await update.message.reply_text("❌ 동기화 먼저 진행하세요")
            await update.message.reply_text(f"📣 {len(m_list)}명 호출 시작")
            for i in range(0, len(m_list), 10):
                mentions = [f"<a href='tg://user?id={mid}'>{mname}</a>" for mid, mname in m_list[i:i+10]]
                await context.bot.send_message(chat_id, " ".join(mentions), parse_mode="HTML")
                await asyncio.sleep(1.2)
            return

    if uid in ADMIN_LIST and update.effective_chat.type == "private":
        if text in ['/설정', '/리스트', '/삭제', '/스케줄']:
            btns = [[InlineKeyboardButton("📁 공용 설정", callback_data="set_room:common")]]
            for r in list(col_members.find()):
                if "room_name" in r: btns.append([InlineKeyboardButton(f"🏠 {r['room_name']}", callback_data=f"set_room:{r['chat_id']}")])
            return await update.message.reply_text("📂 관리 대상 선택", reply_markup=InlineKeyboardMarkup(btns))
        
        raw_html = update.message.caption_html or update.message.text_html or ""
        if update.message.photo or any(x in raw_html.lower() for x in ["/personal", "/스케줄등록"]):
            m_id = update.message.media_group_id or f"s_{update.message.message_id}"
            if update.message.photo:
                if m_id not in media_group_cache: media_group_cache[m_id] = {"ids": [], "caption": "", "task": None}
                media_group_cache[m_id]["ids"].append(update.message.photo[-1].file_id)
                if raw_html: media_group_cache[m_id]["caption"] = raw_html
                if media_group_cache[m_id]["task"]: media_group_cache[m_id]["task"].cancel()
                media_group_cache[m_id]["task"] = asyncio.create_task(save_logic(chat_id, context, m_id, uid))
            else: await save_logic(chat_id, context, None, uid, update.message)
            return

    if text.startswith(('/', '!')):
        cmd = re.sub(r"^[ /!]+", "", text.split()[0]).strip()
        room = col_members.find_one({"chat_id": str(chat_id)})
        target = (room.get("local_commands", {}).get(cmd) if room else None) or col_main.find_one({"id": "bot_main_data"}).get("commands", {}).get(cmd)
        if target: await send_custom_output(context.bot, chat_id, target)

async def save_logic(chat_id, context, m_id, uid, message=None):
    if m_id:
        try: await asyncio.sleep(4.0)
        except asyncio.CancelledError: return
    if m_id and m_id not in media_group_cache: return
    raw_html = media_group_cache[m_id]["caption"] if m_id else (message.caption_html or message.text_html or "")
    sess = col_sessions.find_one({"admin_id": uid}); t_id = sess.get('target_chat_id') if sess else None
    if not t_id or not raw_html: return
    try:
        if "/스케줄등록" in raw_html:
            # 외곽 코드 태그 강제 전멸 처리
            raw_html = re.sub(r'^<code[^>]*>', '', raw_html.strip())
            raw_html = re.sub(r'</code>$', '', raw_html.strip())
            raw_html = re.sub(r'^<pre[^>]*>', '', raw_html.strip())
            raw_html = re.sub(r'</pre>$', '', raw_html.strip())

            h = [p.strip() for p in raw_html.split("/스케줄등록", 1)[1].strip().split("|", 4)]
            intv_part = h[4].split(None, 1)
            intv_raw = intv_part[0]
            content = intv_part[1] if len(intv_part) > 1 else ""
            
            def extract_num(t): return re.sub(r'[^0-9]', '', clean_tags(t))
            def clean_meta(t): return clean_tags(t)
            
            now = datetime.now(KST)
            data = {
                "chat_id": t_id, 
                "name": clean_meta(h[0]), 
                "start_dt": extract_num(h[1]), 
                "end_dt": extract_num(h[2]), 
                "slot_start": extract_num(h[3])[:4], 
                "slot_end": extract_num(h[3])[-4:], 
                "interval": int(extract_num(intv_raw)), 
                "last_run_ts": now.timestamp(), 
                "data": {"photos": (media_group_cache[m_id]["ids"] if m_id else []), "caption": balance_html(content.strip())}
            }
            col_sched.insert_one(data); await context.bot.send_message(chat_id, f"✅ {clean_meta(h[0])} 예약 완료")
        elif "/personal" in raw_html:
            m = re.search(r"/personal\s+(\S+)\s*(.*)", raw_html, re.IGNORECASE | re.DOTALL)
            key, content = clean_tags(m.group(1)), m.group(2)
            msg, btn = content.rsplit("---", 1) if "---" in content else (content, "")
            cmd_data = {"photos": (media_group_cache[m_id]["ids"] if m_id else []), "caption": balance_html(msg.strip()), "buttons": re.sub('<[^<]+?>', '', btn).strip()}
            if t_id == "common": col_main.update_one({"id": "bot_main_data"}, {"$set": {f"commands.{key}": cmd_data}}, upsert=True)
            else: col_members.update_one({"chat_id": t_id}, {"$set": {f"local_commands.{key}": cmd_data}}, upsert=True)
            await context.bot.send_message(chat_id, f"✅ {key} 저장 완료")
    except Exception as e: 
        await context.bot.send_message(chat_id, f"❌ 오류 발생 {clean_tags(str(e))}")
    if m_id in media_group_cache: del media_group_cache[m_id]

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query, uid = update.callback_query, update.callback_query.from_user.id
    if uid not in ADMIN_LIST: return
    data = query.data
    if data.startswith("set_room:"):
        r_id = data.split(":")[1]; col_sessions.update_one({"admin_id": uid}, {"$set": {"target_chat_id": r_id}}, upsert=True)
        await query.edit_message_text(f"🎯 활성화 ID {r_id}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📋 리스트", callback_data=f"show_list:{r_id}"), InlineKeyboardButton("⏰ 스케줄", callback_data=f"show_sched:{r_id}")]]))
    elif data.startswith("show_list:"):
        r_id = data.split(":")[1]
        target = col_main.find_one({"id": "bot_main_data"}).get("commands", {}) if r_id == "common" else (col_members.find_one({"chat_id": r_id}).get("local_commands", {}) or {})
        btns = [[InlineKeyboardButton(f"🗑 {k}", callback_data=f"del:{r_id}:{k}")] for k in target.keys()]
        btns.append([InlineKeyboardButton("🔙", callback_data="back")]); await query.edit_message_text("🗑 삭제 선택", reply_markup=InlineKeyboardMarkup(btns))
    elif data.startswith("show_sched:"):
        r_id = data.split(":")[1]
        btns = [[InlineKeyboardButton(f"🗑 {s['name']}", callback_data=f"dsched:{s['_id']}")] for s in list(col_sched.find({"chat_id": r_id}))]
        btns.append([InlineKeyboardButton("🔙", callback_data="back")]); await query.edit_message_text("⏰ 스케줄 목록", reply_markup=InlineKeyboardMarkup(btns))
    elif data.startswith("del:"):
        _, r_id, k = data.split(":", 2)
        if r_id == "common": col_main.update_one({"id": "bot_main_data"}, {"$unset": {f"commands.{k}": ""}})
        else: col_members.update_one({"chat_id": r_id}, {"$unset": {f"local_commands.{k}": ""}})
        await query.answer("완료"); await handle_callback(update, context)
    elif data.startswith("dsched:"):
        col_sched.delete_one({"_id": ObjectId(data.split(":")[1])}); await query.answer("삭제 완료"); await handle_callback(update, context)
    elif data == "back":
        btns = [[InlineKeyboardButton("📁 공용", callback_data="set_room:common")]] + [[InlineKeyboardButton(f"🏠 {r['room_name']}", callback_data=f"set_room:{r['chat_id']}") ] for r in list(col_members.find()) if "room_name" in r]
        await query.edit_message_text("📂 대상 선택", reply_markup=InlineKeyboardMarkup(btns))

async def post_init(application):
    await userbot.start()
    asyncio.create_task(custom_scheduler_loop(application))

if __name__ == "__main__":
    threading.Thread(target=lambda: Flask(__name__).run(host='0.0.0.0', port=10000), daemon=True).start()
    app = ApplicationBuilder().token(TOKEN).post_init(post_init).build()
    app.add_handler(MessageHandler(filters.ALL, handle_message)); app.add_handler(CallbackQueryHandler(handle_callback))
    app.run_polling()
