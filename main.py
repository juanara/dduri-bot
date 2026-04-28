import os, re, threading, asyncio, logging, random, html, json, requests
from datetime import datetime, timedelta, timezone
from telegram import Update, InputMediaPhoto, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes, CallbackQueryHandler
from flask import Flask
from pymongo import MongoClient
from bson.objectid import ObjectId

# 1. 로그 및 서버 설정
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)
KST = timezone(timedelta(hours=9))

flask_app = Flask(__name__)
@flask_app.route('/')
def health_check(): return "Bot is running!", 200

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    flask_app.run(host='0.0.0.0', port=port)

# 2. 환경 변수 로드
TOKEN = os.getenv("TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "8472713103"))
WEATHER_API_KEY = os.getenv("WEATHER_API_KEY")
MONGO_URL = os.getenv("MONGO_URL")

# 3. MongoDB 연결
client = MongoClient(MONGO_URL)
mongodb = client['dduri_bot_db']
col_main, col_members, col_sched, col_sessions = mongodb['settings'], mongodb['members'], mongodb['schedules'], mongodb['admin_sessions']

media_group_cache = {}
last_run_cache = {}

def get_admin_session(admin_id):
    sess = col_sessions.find_one({"admin_id": admin_id})
    return sess['target_chat_id'] if sess else None

def set_admin_session(admin_id, chat_id):
    col_sessions.update_one({"admin_id": admin_id}, {"$set": {"target_chat_id": str(chat_id)}}, upsert=True)

def load_bot_data():
    data = col_main.find_one({"id": "bot_main_data"})
    return data if data else {"commands": {}}

def save_bot_data(commands):
    col_main.update_one({"id": "bot_main_data"}, {"$set": {"commands": commands}}, upsert=True)

# [자체 스케줄러 엔진] ⭐ 시간 문자열 비교로 UTC 버그 완전 해결
async def custom_scheduler_loop(application):
    await asyncio.sleep(5)
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
                    if s['chat_id'] == "common":
                        for r in list(col_members.find()): await send_custom_output(bot, r['chat_id'], s['data'])
                    else: await send_custom_output(bot, s['chat_id'], s['data'])
        except Exception: pass
        await asyncio.sleep(25)

# [메시지 핸들러] ⭐ 선배님의 필터/리액션/명령어 100% 통합
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global media_group_cache
    if not update.message: return
    uid, text = update.effective_user.id, update.message.text or ""
    cap_html = update.message.caption_html or ""
    clean_text = re.sub(r'[^가-힣a-zA-Z0-9]', '', text).lower()
    text_lower, chat_id = text.lower(), update.effective_chat.id
    chat_title = update.effective_chat.title or "개인"
    name = html.escape(update.message.from_user.first_name)
    is_private = update.effective_chat.type == "private"

    # [수집]
    if not is_private and not update.message.from_user.is_bot:
        col_members.update_one({"chat_id": str(chat_id)}, {"$set": {"room_name": chat_title, f"users.{uid}": name}, "$inc": {"msg_count": 1}}, upsert=True)

    if not update.message.from_user.is_bot:
        # 하우돈 필터 리스트 (38개 완벽 보존 ⭐)
        bad_words = ["일베", "벌레", "노무", "무현", "노무현", "노무쿤", "무현쿤", "노지금무라현노", "지금무라현노", "무라현노", "운지", "운q지", "무q현", "니q노", "니노", "부엉", "부엉이바위", "봉하마을", "봉하", "섹스", "스섹", "쎅", "빨통", "섹q스", "스q섹", "응디", "응q디", "응디시티", "엠씨무현", "mc무현", "엠씨현무", "mc현무", "엠q씨현q무", "노알라", "슨상님", "홍어", "통구이", "중력"]
        if any(w in text_lower for w in bad_words) or any(w in clean_text for w in bad_words):
            if os.path.exists("2.webm"):
                try: 
                    with open("2.webm", "rb") as f: await context.bot.send_sticker(chat_id, f)
                except: pass
            await update.message.reply_text(f"<tg-spoiler>하우돈 검거 👮‍♂️</tg-spoiler>", parse_mode="HTML")
            return 

        # ㅅ 리액션 엔진 (완벽 보존 ⭐)
        s_count = text.count('ㅅ')
        if ("분부니" in text and s_count >= 6) or ("뷰니" in text and s_count >= 5):
            await update.message.reply_text("대여왕 강림!!! 👑 ㅅㅅㅅㅅ", parse_mode="HTML")
            return
        elif "무욱자" in text and s_count >= 4:
            await update.message.reply_text("우욱자갓 ㅅㅅㅅㅅ 미친 폼!! 🔥")
            return
        elif s_count >= 9 or text.count('ㅆ') >= 9:
            accel = ["폼 미쳤다ㄷㄷ 오늘 텐션 개오짐!! 🔥", "완전 럭키비키잖아!! ✨", "이거지ㅋㅋ 분위기 찢었다!! 🚀", "도파민 폭발함!! 🧨", "갓벽하다 진짜ㅋㅋ 💎"]
            await update.message.reply_text(random.choice(accel))
            return

    # [관리자 전용]
    if uid == ADMIN_ID and is_private:
        if text.startswith(('/설정', '/리스트', '/삭제', '/스케줄')):
            btns = [[InlineKeyboardButton("📁 [공용] 설정", callback_data="set_room:common")]]
            for r in list(col_members.find()):
                if "room_name" in r: btns.append([InlineKeyboardButton(f"🏠 {r['room_name']}", callback_data=f"set_room:{r['chat_id']}")])
            return await update.message.reply_text("📂 관리할 방 선택:", reply_markup=InlineKeyboardMarkup(btns))

        if update.message.photo or any(x in (text+cap_html).lower() for x in ["/personal", "/이벤트설정", "/스케줄등록"]):
            m_id = update.message.media_group_id or f"s_{update.message.message_id}"
            if update.message.photo:
                if m_id not in media_group_cache:
                    media_group_cache[m_id] = {"ids": [], "caption": update.message.caption_html or "", "task": None}
                media_group_cache[m_id]["ids"].append(update.message.photo[-1].file_id)
                if media_group_cache[m_id]["task"]: media_group_cache[m_id]["task"].cancel()
                media_group_cache[m_id]["task"] = asyncio.create_task(save_logic_with_delay(chat_id, context, m_id))
            else: await save_logic_with_delay(chat_id, context, None, update.message)
            return

    # [호출]
    if text.startswith(('/', '!')):
        cmd = re.sub(r"^[ /!]+", "", text.split()[0]).strip()
        room = col_members.find_one({"chat_id": str(chat_id)})
        target = room.get("local_commands", {}).get(cmd) if room else None
        if target: await send_custom_output(context.bot, chat_id, target)
        elif cmd in load_bot_data().get("commands", {}): await send_custom_output(context.bot, chat_id, load_bot_data()["commands"][cmd])

# [저장 로직] ⭐ 사진 묶음 3.5초 대기 & 무삭제 저장
async def save_logic_with_delay(chat_id, context, m_id, message=None):
    if m_id: await asyncio.sleep(3.5)
    raw_html = media_group_cache[m_id]["caption"] if m_id else (message.caption_html or message.text_html or "")
    if not raw_html: return
    target_chat_id = get_admin_session(ADMIN_ID)
    if not target_chat_id: return await context.bot.send_message(chat_id, "⚠️ 방을 먼저 선택하세요.")

    try:
        # 1. 스케줄 등록 (정밀 파서 ⭐)
        if "/스케줄등록" in raw_html:
            core = raw_html.split("/스케줄등록", 1)[1].strip()
            h = [p.strip() for p in core.split("|", 4)]
            intv, content = h[4].split(None, 1)
            photos = media_group_cache[m_id]["ids"] if m_id else []
            data = {"chat_id": target_chat_id, "name": h[0], "start_dt": h[1], "end_dt": h[2], "slot_start": h[3].replace("-","").strip()[:4], "slot_end": h[3].replace("-","").strip()[-4:], "interval": int(intv), "data": {"photos": photos, "caption": content.strip()}}
            res = col_sched.insert_one(data)
            last_run_cache[str(res.inserted_id)] = datetime.now(KST) - timedelta(minutes=int(intv))
            await context.bot.send_message(chat_id, f"⏰ [{h[0]}] 예약 완료! (사진 {len(photos)}장)")
        
        # 2. 명령어/이벤트 (HTML 이모지 보존 ⭐)
        else:
            if "/이벤트설정" in raw_html: key, content = "_event_celebration_", raw_html.split("/이벤트설정", 1)[1].strip()
            elif "/personal" in raw_html:
                match = re.search(r"/personal\s+(\S+)\s*(.*)", raw_html, re.IGNORECASE | re.DOTALL)
                if match: key, content = match.group(1), match.group(2)
                else: return
            else: return

            msg, btn = content.rsplit("---", 1) if "---" in content else (content, "")
            photos = media_group_cache[m_id]["ids"] if m_id else []
            cmd_data = {"photos": photos, "caption": msg.strip(), "buttons": re.sub('<[^<]+?>', '', btn).strip()}

            if target_chat_id == "common":
                cmds = load_bot_data().get("commands", {}); cmds[key] = cmd_data; save_bot_data(cmds)
            else: col_members.update_one({"chat_id": target_chat_id}, {"$set": {f"local_commands.{key}": cmd_data}})
            await context.bot.send_message(chat_id, f"✅ [{key}] 저장 완료! (사진 {len(photos)}장)")
    except Exception as e: await context.bot.send_message(chat_id, f"❌ 에러: {e}")
    if m_id: del media_group_cache[m_id]

async def send_custom_output(bot, chat_id, data):
    try:
        photos, caption, cid = data.get("photos", []), data.get("caption", ""), str(chat_id)
        markup = None
        if data.get("buttons"):
            keyboard = [[InlineKeyboardButton(b.split('|')[0].strip(), url=b.split('|')[1].strip()) for b in line.split('&&') if '|' in b] for line in data["buttons"].split('\n')]
            markup = InlineKeyboardMarkup(keyboard) if any(keyboard) else None
        
        if not photos: await bot.send_message(cid, caption, parse_mode="HTML", reply_markup=markup)
        elif len(photos) == 1: await bot.send_photo(cid, photos[0], caption=caption, parse_mode="HTML", reply_markup=markup)
        else:
            media = [InputMediaPhoto(photos[0], caption=caption, parse_mode="HTML")] + [InputMediaPhoto(f) for f in photos[1:]]
            await bot.send_media_group(cid, media)
            if markup: await bot.send_message(cid, "⚡️ 버튼 확인", reply_markup=markup)
    except: pass

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.data.startswith("set_room:"):
        r_id = query.data.split(":")[1]
        set_admin_session(ADMIN_ID, r_id)
        await query.edit_message_text(f"🎯 설정 모드 활성화 (ID: {r_id})")

if __name__ == "__main__":
    if TOKEN and MONGO_URL:
        threading.Thread(target=run_flask, daemon=True).start()
        app = ApplicationBuilder().token(TOKEN).build()
        app.add_handler(MessageHandler(filters.ALL, handle_message))
        app.add_handler(CallbackQueryHandler(handle_callback))
        app.job_queue.run_once(lambda ctx: asyncio.create_task(custom_scheduler_loop(app)), 1)
        app.run_polling()
