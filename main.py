import os, re, threading, asyncio, logging, html, requests
from datetime import datetime, timedelta, timezone
from telegram import Update, InputMediaPhoto, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes, CallbackQueryHandler
from flask import Flask
from pymongo import MongoClient
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.types import User
from bson.objectid import ObjectId

# 1. 환경 및 로그 설정
logging.basicConfig(level=logging.INFO)
KST = timezone(timedelta(hours=9))

# 환경 변수 로드
TOKEN = os.getenv("TOKEN")
API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH")
STRING_SESSION = os.getenv("STRING_SESSION")
MONGO_URL = os.getenv("MONGO_URL")
WEATHER_API_KEY = os.getenv("WEATHER_API_KEY")

# 멀티 관리자 설정 대응
ADMIN_ID_STR = os.getenv("ADMIN_ID", "8092185425")
ADMIN_LIST = [int(i.strip()) for i in ADMIN_ID_STR.split(",") if i.strip()]

client = MongoClient(MONGO_URL)
mongodb = client['dduri3_bot_db']
col_main, col_members, col_sched, col_sessions = mongodb['settings'], mongodb['members'], mongodb['schedules'], mongodb['admin_sessions']

# 텔레톤 유저봇 및 캐시 초기화
userbot = TelegramClient(StringSession(STRING_SESSION), API_ID, API_HASH)
media_group_cache = {}

# 엔진 1 HTML 태그 밸런서
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

# 엔진 2 출력 엔진
async def send_custom_output(bot, chat_id, data, title=""):
    try:
        c_str = str(chat_id).strip()
        cid = int(c_str) if (c_str.isdigit() or (c_str.startswith('-') and c_str[1:].isdigit())) else c_str
        
        photos = data.get("photos", [])
        caption = f"<b>{title}</b>\n\n{data['caption']}" if title else data['caption']
        
        markup = None
        if data.get("buttons"):
            btns = [[InlineKeyboardButton(b.split('|')[0].strip(), url=b.split('|')[1].strip()) for b in line.split('&&') if '|' in b] for line in data["buttons"].split('\n')]
            if btns and btns[0]: markup = InlineKeyboardMarkup(btns)
        
        if not photos: 
            await bot.send_message(cid, caption, parse_mode="HTML", reply_markup=markup)
        elif len(photos) == 1: 
            await bot.send_photo(cid, photos[0], caption=caption, parse_mode="HTML", reply_markup=markup)
        else:
            media = [InputMediaPhoto(photos[0], caption=caption, parse_mode="HTML")] + [InputMediaPhoto(f) for f in photos[1:]]
            await bot.send_media_group(cid, media)
            if markup: await bot.send_message(cid, "⚡️ 버튼 확인", reply_markup=markup)
    except Exception as e:
        logging.error(f"Output Error: {e}")

# 엔진 3 스케줄러 루프
async def custom_scheduler_loop(application):
    await asyncio.sleep(10)
    bot = application.bot
    while True:
        try:
            now = datetime.now(KST)
            now_ts = now.timestamp()
            now_date, now_time = now.strftime("%Y%m%d"), now.strftime("%H%M")
            now_str = now.strftime("%Y-%m-%d %H:%M")
            
            for s in list(col_sched.find()):
                sid = str(s['_id'])
                if not (s['start_dt'] <= now_str <= s['end_dt']):
                    if now_str > s['end_dt']: col_sched.delete_one({"_id": s['_id']})
                    continue
                if not (s['slot_start'] <= now_time <= s['slot_end']): continue
                
                next_run_ts = s.get('next_run_ts')
                if next_run_ts is None:
                    col_sched.update_one({"_id": s['_id']}, {"$set": {"next_run_ts": now_ts + s['interval'] * 60}})
                    continue
                    
                if now_ts >= next_run_ts:
                    col_sched.update_one({"_id": s['_id']}, {"$set": {"next_run_ts": next_run_ts + s['interval'] * 60}})
                    if s['chat_id'] == "common":
                        for r in list(col_members.find()): await send_custom_output(bot, r['chat_id'], s['data'])
                    else: await send_custom_output(bot, s['chat_id'], s['data'])
        except Exception as e:
            logging.error(f"Scheduler Loop Error: {e}")
        await asyncio.sleep(20)

# 엔진 4 저장 로직
async def save_logic_with_delay(chat_id, context, m_id, message=None):
    if m_id: await asyncio.sleep(3.5)
    raw_html = media_group_cache[m_id]["caption"] if m_id else (message.caption_html or message.text_html or "")
    sess = col_sessions.find_one({"admin_id": {"$in": ADMIN_LIST}})
    t_id = sess['target_chat_id'] if sess else None
    if not t_id: return await context.bot.send_message(chat_id, "⚠️ 설정 명령어로 방을 먼저 선택하세요")
    
    try:
        if "/스케줄등록" in raw_html:
            cleaned = raw_html.strip()
            cleaned = re.sub(r'</?(pre|code)[^>]*>', '', cleaned)
            
            match = re.search(r'/스케줄등록\s*([^|]+)\|([^|]+)\|([^|]+)\|([^|]+)\|(\d+)\s*(.*)', cleaned, re.DOTALL)
            if not match: raise ValueError("스케줄 등록 형식이 올바르지 않습니다 명확히 파이프 기호로 구분하여 입력하세요")
            
            name = clean_tags(match.group(1))
            start_dt = clean_tags(match.group(2))
            end_dt = clean_tags(match.group(3))
            time_range = clean_tags(match.group(4))
            interval = int(match.group(5))
            content = match.group(6).strip()
            
            time_parts = re.split(r'[~-]', time_range)
            if len(time_parts) >= 2:
                s_part = re.sub(r'[^0-9]', '', time_parts[0])
                e_part = re.sub(r'[^0-9]', '', time_parts[1])
                if len(s_part) == 3: s_part = "0" + s_part
                if len(e_part) == 3: e_part = "0" + e_part
                slot_start = s_part[:4].zfill(4)
                slot_end = e_part[:4].zfill(4)
            else:
                digits = re.sub(r'[^0-9]', '', time_range)
                slot_start = digits[:4].zfill(4)
                slot_end = digits[-4:].zfill(4)
            
            now_ts = datetime.now(KST).timestamp()
            data = {
                "chat_id": t_id, 
                "name": name, 
                "start_dt": start_dt, 
                "end_dt": end_dt, 
                "slot_start": slot_start, 
                "slot_end": slot_end, 
                "interval": interval, 
                "next_run_ts": now_ts + interval * 60, 
                "data": {"photos": (media_group_cache[m_id]["ids"] if m_id else []), "caption": balance_html(content)}
            }
            col_sched.insert_one(data); await context.bot.send_message(chat_id, f"⏰ {name} 예약 완료")
        elif "/personal" in raw_html:
            m = re.search(r"/personal\s+(\S+)\s*(.*)", raw_html, re.IGNORECASE | re.DOTALL)
            key, content = (m.group(1), m.group(2)) if m else (None, None)
            if not key: return
            msg, btn = content.rsplit("---", 1) if "---" in content else (content, "")
            cmd_data = {"photos": (media_group_cache[m_id]["ids"] if m_id else []), "caption": balance_html(msg.strip()), "buttons": re.sub('<[^<]+?>', '', btn).strip()}
            if t_id == "common": col_main.update_one({"id": "bot_main_data"}, {"$set": {f"commands.{key}": cmd_data}}, upsert=True)
            else: col_members.update_one({"chat_id": t_id}, {"$set": {f"local_commands.{key}": cmd_data}}, upsert=True)
            await context.bot.send_message(chat_id, f"✅ {key} 저장 완료")
    except Exception as e: 
        await context.bot.send_message(chat_id, f"❌ 에러 발생 {clean_tags(str(e))}")
    if m_id in media_group_cache: del media_group_cache[m_id]

# 메인 핸들러
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message: return
    uid, text, chat_id = update.effective_user.id, (update.message.text or "").strip(), update.effective_chat.id
    
    # 동기화 및 전체공지 명령어 복구 구역
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

    # 실시간 국내 날씨 정보 인터페이스 10초 타임아웃 적용
    if text.startswith(('/날씨', '!날씨')):
        parts = text.split(None, 1)
        input_city = parts[1].strip() if len(parts) > 1 else "수원"
        
        ko_to_en = {
            "서울": "Seoul", "부산": "Busan", "대구": "Daegu", "인천": "Incheon",
            "광주": "Gwangju", "대전": "Daejeon", "울산": "Ulsan", "세종": "Sejong",
            "수원": "Suwon", "성남": "Seongnam", "고양": "Goyang", "용인": "Yongin",
            "부천": "Bucheon", "안산": "Ansan", "안양": "Anyang", "남양주": "Namyangju",
            "화성": "Hwaseong", "평택": "Pyeongtaek", "의정부": "Uijeongbu", "시흥": "Siheung",
            "파주": "Paju", "김포": "Gimpo", "광명": "Gwangmyeong", "군포": "Gunpo",
            "오산": "Osan", "이천": "Icheon", "양주": "Yangju", "안성": "Anseong",
            "구리": "Guri", "포천": "Pocheon", "의왕": "Uiwang", "하남": "Hanam",
            "여주": "Yeoju", "동두천": "Dongducheon", "과천": "Gwacheon", "춘천": "Chuncheon",
            "원주": "Wonju", "강릉": "Gangneung", "동해": "Donghae", "태백": "Taebaek",
            "속초": "Sokcho", "삼척": "Samcheok", "청주": "Cheongju", "충주": "Chungju",
            "제천": "Jecheon", "천안": "Cheonan", "공주": "Gongju", "보령": "Boryeong",
            "아산": "Asan", "서산": "Seosan", "논산": "Nonsan", "계룡": "Gyeryong",
            "당진": "Dangjin", "전주": "Jeonju", "군산": "Gunsan", "익산": "Iksan",
            "정읍": "Jeongeup", "남원": "Namwon", "김제": "Gimje", "목포": "Mokpo",
            "여수": "Yeosu", "순천": "Suncheon", "나주": "Naju", "광양": "Gwangyang",
            "포항": "Pohang", "경주": "Gyeongju", "김천": "Gimcheon", "안동": "Andong",
            "구미": "Gumi", "영주": "Yeongju", "영천": "Yeongcheon", "상주": "Sangju",
            "문경": "Mungyeong", "경산": "Gyeongsan", "창원": "Changwon", "진주": "Jinju",
            "통영": "Tongyeong", "사천": "Sacheon", "김해": "Gimhae", "밀양": "Miryang",
            "거제": "Geoje", "양산": "Yangsan", "제주": "Jeju", "서귀포": "Seogwipo"
        }
        
        search_city = input_city.replace("특별시", "").replace("광역시", "").replace("특별자치시", "").replace("시", "").strip()
        api_city = ko_to_en.get(search_city, input_city)
        
        if not WEATHER_API_KEY:
            await update.message.reply_text("⚠️ 날씨 API 키가 렌더 환경변수에 설정되지 않았습니다")
            return
        try:
            res = requests.get(f"http://api.openweathermap.org/data/2.5/weather?q={api_city}&appid={WEATHER_API_KEY}&units=metric&lang=kr", timeout=10).json()
            if str(res.get("cod")) == "200":
                w_desc = res["weather"][0]["description"]
                temp = res["main"]["temp"]
                humidity = res["main"]["humidity"]
                msg = f"☀️ {input_city} 실시간 날씨 정보\n\n상태 현재 {w_desc}\n기온 현재 {temp}도\n습도 현재 {humidity}%"
                await update.message.reply_text(msg)
            else:
                await update.message.reply_text("❌ 도시 이름을 찾을 수 없습니다 정확한 시 구 단위로 입력하세요")
        except Exception as weather_err:
            await update.message.reply_text(f"❌ 날씨 시스템 연동 장애 발생 {weather_err}")
        return

    # 관리자 개인 DM 설정 모드
    if uid in ADMIN_LIST and update.effective_chat.type == "private":
        if text.startswith(('/설정', '/리스트', '/삭제')):
            btns = [[InlineKeyboardButton("📁 공용 설정", callback_data="set_room:common")]]
            for r in list(col_members.find()):
                if "room_name" in r: btns.append([InlineKeyboardButton(f"🏠 {r['room_name']}", callback_data=f"set_room:{r['chat_id']}")])
            return await update.message.reply_text("📂 관리할 방 선택:", reply_markup=InlineKeyboardMarkup(btns))
        
        if update.message.photo or "/personal" in text or "/스케줄등록" in text:
            m_id = update.message.media_group_id or f"s_{update.message.message_id}"
            if update.message.photo:
                if m_id not in media_group_cache: media_group_cache[m_id] = {"ids": [], "caption": update.message.caption_html or "", "task": None}
                media_group_cache[m_id]["ids"].append(update.message.photo[-1].file_id)
                if media_group_cache[m_id]["task"]: media_group_cache[m_id]["task"].cancel()
                media_group_cache[m_id]["task"] = asyncio.create_task(save_logic_with_delay(chat_id, context, m_id))
            else: await save_logic_with_delay(chat_id, context, None, update.message)
            return

    # 커맨드 실행
    if text.startswith(('/', '!')):
        cmd = re.sub(r"^[ /!]+", "", text.split()[0]).strip()
        room = col_members.find_one({"chat_id": str(chat_id)})
        main_data = col_main.find_one({"id": "bot_main_data"}) or {}
        target = (room.get("local_commands", {}).get(cmd) if room else None) or main_data.get("commands", {}).get(cmd)
        if target: await send_custom_output(context.bot, chat_id, target)

# 콜백 핸들러
async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; data = query.data
    if query.from_user.id not in ADMIN_LIST: return
    
    if data.startswith("set_room:"):
        r_id = data.split(":")[1]
        col_sessions.update_one({"admin_id": query.from_user.id}, {"$set": {"target_chat_id": r_id}}, upsert=True)
        btns = [[InlineKeyboardButton("📋 커맨드 목록", callback_data=f"show_list:{r_id}"), InlineKeyboardButton("⏰ 스케줄 목록", callback_data=f"show_sched:{r_id}")]]
        await query.edit_message_text(f"🎯 활성화됨 ID {r_id}\n이제 사진이나 메시지를 보내 저장하세요.", reply_markup=InlineKeyboardMarkup(btns))
    elif data.startswith("show_list:"):
        r_id = data.split(":")[1]
        main_data = col_main.find_one({"id": "bot_main_data"}) or {}
        target = main_data.get("commands", {}) if r_id == "common" else (col_members.find_one({"chat_id": r_id}).get("local_commands", {}) if col_members.find_one({"chat_id": r_id}) else {})
        btns = [[InlineKeyboardButton(f"🗑 {k}", callback_data=f"del:{r_id}:{k}")] for k in target.keys()]
        btns.append([InlineKeyboardButton("🔙 뒤로", callback_data="back_to_rooms")])
        if btns and btns[0]: await query.edit_message_text("🗑 삭제할 커맨드 선택:", reply_markup=InlineKeyboardMarkup(btns))
    elif data.startswith("show_sched:"):
        r_id = data.split(":")[1]
        btns = [[InlineKeyboardButton(f"🗑 {s['name']}", callback_data=f"dsched:{s['_id']}")] for s in list(col_sched.find({"chat_id": r_id}))]
        btns.append([InlineKeyboardButton("🔙 뒤로", callback_data="back_to_rooms")])
        if btns and btns[0]: await query.edit_message_text("⏰ 스케줄 목록", reply_markup=InlineKeyboardMarkup(btns))
    elif data.startswith("del:"):
        _, r_id, k = data.split(":", 2)
        if r_id == "common": col_main.update_one({"id": "bot_main_data"}, {"$unset": {f"commands.{k}": ""}})
        else: col_members.update_one({"chat_id": r_id}, {"$unset": {f"local_commands.{k}": ""}})
        await query.answer("삭제 완료!")
        main_data = col_main.find_one({"id": "bot_main_data"}) or {}
        target = main_data.get("commands", {}) if r_id == "common" else (col_members.find_one({"chat_id": r_id}).get("local_commands", {}) if col_members.find_one({"chat_id": r_id}) else {})
        btns = [[InlineKeyboardButton(f"🗑 {key}", callback_data=f"del:{r_id}:{key}")] for key in target.keys()]
        btns.append([InlineKeyboardButton("🔙 뒤로", callback_data="back_to_rooms")])
        await query.edit_message_text("🗑 삭제할 커맨드 선택:", reply_markup=InlineKeyboardMarkup(btns))
    elif data.startswith("dsched:"):
        _, s_id = data.split(":", 1)
        sched_item = col_sched.find_one({"_id": ObjectId(s_id)})
        r_id = sched_item['chat_id'] if sched_item else "common"
        col_sched.delete_one({"_id": ObjectId(s_id)})
        await query.answer("삭제 완료")
        btns = [[InlineKeyboardButton(f"🗑 {s['name']}", callback_data=f"dsched:{s['_id']}")] for s in list(col_sched.find({"chat_id": r_id}))]
        btns.append([InlineKeyboardButton("🔙 뒤로", callback_data="back_to_rooms")])
        await query.edit_message_text("⏰ 스케줄 목록", reply_markup=InlineKeyboardMarkup(btns))
    elif data == "back_to_rooms":
        btns = [[InlineKeyboardButton("📁 공용 설정", callback_data="set_room:common")]]
        for r in list(col_members.find()):
            if "room_name" in r: btns.append([InlineKeyboardButton(f"🏠 {r['room_name']}", callback_data=f"set_room:{r['chat_id']}")])
        await query.edit_message_text("📂 관리할 방 선택:", reply_markup=InlineKeyboardMarkup(btns))

# Flask 헬스체크
flask_app = Flask(__name__)
@flask_app.route('/')
def home(): return "OK", 200

def run_flask():
    flask_app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)))

# 비동기 인스턴스 정석 초기화 모듈
async def post_init(application):
    await userbot.start()
    asyncio.create_task(custom_scheduler_loop(application))

if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    app = ApplicationBuilder().token(TOKEN).post_init(post_init).build()
    app.add_handler(MessageHandler(filters.ALL, handle_message))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.run_polling()
