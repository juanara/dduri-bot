import os, re, threading, asyncio, logging, random, html, json, requests
from datetime import datetime, timedelta, timezone # pytz 대신 내장 모듈 사용 ⭐
from telegram import Update, InputMediaPhoto, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes, CallbackQueryHandler
from flask import Flask
from pymongo import MongoClient
from bson.objectid import ObjectId

# 1. 로그 및 서버 설정
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# 한국 표준시(KST) 설정 (GMT+9) ⭐ 외부 라이브러리 없이 구현
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
col_main = mongodb['settings']
col_members = mongodb['members']
col_sched = mongodb['schedules']

admin_sessions = {} # 관리자 설정 세션
media_group_cache = {} # 사진 묶음 수집용

def load_bot_data():
    data = col_main.find_one({"id": "bot_main_data"})
    if not data: return {"commands": {}}
    return data

def save_bot_data(commands):
    col_main.update_one({"id": "bot_main_data"}, {"$set": {"commands": commands}}, upsert=True)

def save_member_and_count(chat_id, user_id, name, chat_title, is_msg=False):
    sid, uid = str(chat_id), str(user_id)
    update_data = {f"users.{uid}": name, "room_name": chat_title}
    if is_msg:
        col_members.update_one({"chat_id": sid}, {"$set": update_data, "$inc": {"msg_count": 1}}, upsert=True)
    else:
        col_members.update_one({"chat_id": sid}, {"$set": update_data, "$setOnInsert": {"msg_count": 0}}, upsert=True)

def get_room_data(chat_id):
    return col_members.find_one({"chat_id": str(chat_id)})

async def is_authorized(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid == ADMIN_ID: return True
    if update.effective_chat.type == "private": return False
    try:
        member = await context.bot.get_chat_member(update.effective_chat.id, uid)
        return member.status in ["administrator", "creator"]
    except: return False

current_data = load_bot_data()
db_commands = current_data.get("commands", {})

# 스케줄 실행 엔진
async def run_scheduled_task(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    sched = col_sched.find_one({"_id": job.data['id']})
    if not sched: return
    
    # 한국 시간 기준으로 현재 시각 계산 ⭐
    now = datetime.now(KST)
    
    # 전체 기간 체크 (UTC 인식을 위해 저장된 시간을 KST로 변환하여 비교)
    start_dt = sched['start_dt'].replace(tzinfo=KST)
    end_dt = sched['end_dt'].replace(tzinfo=KST)
    
    if not (start_dt <= now <= end_dt):
        if now > end_dt:
            col_sched.delete_one({"_id": job.data['id']})
            job.schedule_removal()
        return
    
    # 일일 시간대(Slot) 체크
    curr_t = now.strftime("%H%M")
    if not (sched['slot_start'] <= curr_t <= sched['slot_end']): return
    
    try: await send_custom_output(context, sched['chat_id'], sched['data'])
    except: pass

async def get_realtime_weather(city_input="수원"):
    if not WEATHER_API_KEY: return "❌ API_KEY 누락"
    city_map = {"수원": "Suwon", "서울": "Seoul", "인천": "Incheon", "부산": "Busan", "제주": "Jeju"}
    url = f"http://api.openweathermap.org/data/2.5/weather?q={city_map.get(city_input, city_input)}&appid={WEATHER_API_KEY}&units=metric&lang=kr"
    try:
        data = requests.get(url, timeout=5).json()
        if data.get("cod") == 200:
            return f"📍 <b>{city_input} 날씨</b>\n🌡️ {data['main']['temp']}°C / {data['weather'][0]['description']}"
        return f"❌ '{city_input}' 찾기 실패"
    except: return "⚠️ 오류"

def get_menu_recommendation(command):
    starbucks_30 = ["아이스 아메리카노", "카페 라떼", "자몽 허니 블랙 티", "돌체 라떼", "콜드 브루", "바닐라 크림 콜드 브루", "자바 칩 프라푸치노", "쿨 라임 피지오", "화이트 초콜릿 모카", "카라멜 마키아또", "제주 유기농 말차 라떼", "민트 초콜릿 칩 블렌디드", "더블 에스프레소 칩 프라푸치노", "에스프레소 프라푸치노", "바닐라 플랫 화이트", "카페 모카", "카푸치노", "얼 그레이 티 라떼", "블랙 티 레모네이드 피지오", "핑크 드링크 위드 딸기 아사이", "딸기 아사이 레모네이드", "망고 패션 티 블렌디드", "유자 패션 피지오", "돌체 블랙 밀크 티", "차이 티 라떼", "블론드 바닐라 더블 샷 마키아또", "클래식 밀크 티", "피스타치오 크림 콜드 브루", "오늘의 커피", "바닐라 더블 샷"]
    lunch_30 = ["김치찌개", "된장찌개", "비빔밥", "돈까스", "짜장면", "짬뽕", "제육볶음", "육개장", "칼국수", "수제비", "냉면", "쌀국수", "파스타", "규동", "가츠동", "회덮밥", "부대찌개", "뚝배기불고기", "함박스테이크", "오므라이스", "잔치국수", "텐동", "라멘", "마라탕", "떡볶이", "버거킹", "포케", "초밥", "카레", "고등어구이"]
    if "/커추" in command: return f"☕️ <b>스벅 추천</b>: <b>{random.choice(starbucks_30)}</b>"
    return f"🍴 <b>추천 메뉴</b>: <b>{random.choice(lunch_30)}</b>"

async def delete_messages_later(context, chat_id, message_ids, delay):
    await asyncio.sleep(delay)
    for msg_id in message_ids:
        try: await context.bot.delete_message(chat_id, msg_id)
        except: pass

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global db_commands, media_group_cache, admin_sessions
    if not update.message: return
    uid, text = update.message.from_user.id, update.message.text or ""
    clean_text = re.sub(r'[^가-힣a-zA-Z0-9]', '', text).lower()
    text_lower, chat_id = text.lower(), update.effective_chat.id
    cap_html = update.message.caption_html or ""
    chat_title = update.effective_chat.title or "개인 대화"
    name = html.escape(update.message.from_user.first_name)
    is_private = update.effective_chat.type == "private"

    if not is_private and not update.message.from_user.is_bot:
        is_msg = not text.startswith(('/', '!')) and not cap_html.startswith('/')
        save_member_and_count(chat_id, uid, name, chat_title, is_msg=is_msg)
    
    if update.message.entities:
        for entity in update.message.entities:
            if entity.type == "text_mention": save_member_and_count(chat_id, entity.user.id, html.escape(entity.user.first_name), chat_title)

    if not update.message.from_user.is_bot:
        is_auth = await is_authorized(update, context)
        if is_auth:
            if text_lower == "/카운트확인":
                room = get_room_data(chat_id); cnt = room.get("msg_count", 0) if room else 0
                return await update.message.reply_text(f"📊 <b>{chat_title}</b> 누적: <b>{cnt:,}</b>", parse_mode="HTML")
            if text_lower == "/리스트":
                if is_private:
                    all_rooms = list(col_members.find())
                    summary = [f"🏠 <b>{r.get('room_name','?')}</b>\n인원: {len(r.get('users',{}))}명\n" for r in all_rooms if r]
                    return await update.message.reply_text("📋 <b>전체 방 현황</b>\n\n" + "\n".join(summary or ["데이터 없음"]), parse_mode="HTML")
                else:
                    room = get_room_data(chat_id); members = room.get("users", {}) if room else {}
                    return await update.message.reply_text(f"📋 <b>회원 현황</b>\n🏠 <b>{chat_title}</b>\n인원: {len(members)}명", parse_mode="HTML")
            if text_lower.startswith(("/all", "/전체공지", "/전체멘션")):
                room = get_room_data(chat_id); members = room.get("users", {}) if room else {}
                if not members: return await update.message.reply_text("❌ 멤버 없음")
                m_list = list(members.items())
                for i in range(0, len(m_list), 10):
                    mentions = [f"<a href='tg://user?id={mid}'>{mname}</a>" for mid, mname in m_list[i:i+10]]
                    await context.bot.send_message(chat_id, " ".join(mentions), parse_mode="HTML")
                    await asyncio.sleep(0.5)
                return

        bad_words = ["일베", "벌레", "노무", "무현", "노무현", "노무쿤", "무현쿤", "노지금무라현노", "지금무라현노", "무라현노", "운지", "운q지", "무q현", "니q노", "부엉", "부엉이바위", "봉하", "이기야", "데스웅", "노알라", "슨상님", "홍어", "통구이", "중력", "전라디언", "폭동", "땅크", "엔젤두환", "재앙", "재기", "섹스", "스섹", "빨통", "응디", "응디시티", "엠씨무현", "mc무현", "엠씨현무", "mc현무"]
        if any(w in text_lower for w in bad_words) or any(w in clean_text for w in bad_words):
            rep = await update.message.reply_text(f"<tg-spoiler>하우돈 검거 👮‍♂️</tg-spoiler>", parse_mode="HTML")
            s_msg = None
            if os.path.exists("2.webm"):
                try: 
                    with open("2.webm", "rb") as f: s_msg = await context.bot.send_sticker(chat_id, f)
                except: pass
            asyncio.create_task(delete_messages_later(context, chat_id, [update.message.message_id, rep.message_id, (s_msg.message_id if s_msg else None)], 10.0))
            return 

        s_count = text.count('ㅅ')
        if ("분부니" in text and s_count >= 6) or ("뷰니" in text and s_count >= 5):
            rep = await update.message.reply_text("대여왕 강림!!! 👑 ㅅㅅㅅㅅ", parse_mode="HTML")
            asyncio.create_task(delete_messages_later(context, chat_id, [update.message.message_id, rep.message_id], 10.0))
            return
        elif "무욱자" in text and s_count >= 4:
            return await update.message.reply_text("우욱자갓 ㅅㅅㅅㅅ 미친 폼!! 🔥")
        elif s_count >= 9 or text.count('ㅆ') >= 9:
            accel = ["폼 미쳤다ㄷㄷ 오늘 텐션 개오짐!! 🔥", "완전 럭키비키잖아!! ✨", "이거지ㅋㅋ 분위기 찢었다!! 🚀", "도파민 폭발함!! 🧨", "갓벽하다 진짜ㅋㅋ 💎"]
            return await update.message.reply_text(random.choice(accel))

    if any(text_lower.startswith(c) for c in ["/아메추", "/점메추", "/저메추", "/커추", "/간추", "/날씨"]):
        res = await get_realtime_weather(text.split()[1]) if text_lower.startswith("/날씨") and len(text.split()) > 1 else (await get_realtime_weather("수원") if text_lower.startswith("/날씨") else get_menu_recommendation(text_lower))
        rep = await update.message.reply_text(res, parse_mode="HTML")
        asyncio.create_task(delete_messages_later(context, chat_id, [update.message.message_id, rep.message_id], 5.0))
        return
    if text in ["/주사위", "!주사위"]:
        r = random.randrange(500, 50001, 500); icon = "💎" if r >= 40000 else "🔥" if r >= 10000 else "🎲"
        rep = await update.message.reply_text(f"<b>{name}</b>님의 결과: {icon} <b>{r:,}</b>", parse_mode="HTML")
        asyncio.create_task(delete_messages_later(context, chat_id, [update.message.message_id, rep.message_id], 10.0))
        return

    if uid == ADMIN_ID and is_private:
        if text_lower in ["/설정", "/리스트확인", "/삭제", "/스케줄"]:
            all_rooms = list(col_members.find())
            btns = [[InlineKeyboardButton("📁 [공용] 설정", callback_data="set_room:common")]]
            for r in all_rooms:
                if "room_name" in r: btns.append([InlineKeyboardButton(f"🏠 {r['room_name']} 설정", callback_data=f"set_room:{r['chat_id']}")])
            return await update.message.reply_text("📂 관리할 방을 선택해 주세요:", reply_markup=InlineKeyboardMarkup(btns))

        if update.message.photo:
            m_id = update.message.media_group_id or f"s_{update.message.message_id}"
            if m_id not in media_group_cache: media_group_cache[m_id] = {"ids": [], "caption_html": "", "task": None}
            media_group_cache[m_id]["ids"].append(update.message.photo[-1].file_id)
            if any(x in cap_html.lower() for x in ["/personal", "/이벤트설정", "/스케줄등록"]): media_group_cache[m_id]["caption_html"] = cap_html
            if media_group_cache[m_id]["task"]: media_group_cache[m_id]["task"].cancel()
            media_group_cache[m_id]["task"] = asyncio.create_task(save_logic_with_delay(chat_id, context, m_id))
            return
        if text_lower.startswith(("/personal", "/이벤트설정", "/스케줄등록")):
            await save_logic_with_delay(chat_id, context, None, update.message)
            return

    if not is_private and not update.message.from_user.is_bot:
        room = get_room_data(chat_id)
        if room and room.get("msg_count", 0) > 0 and room.get("msg_count", 0) % 5000 == 0:
            local_evt = room.get("local_commands", {}).get("_event_celebration_")
            target_data = local_evt if local_evt else db_commands.get("_event_celebration_")
            if target_data: await send_custom_output(context, chat_id, target_data, f"🎊 {chat_title} {room['msg_count']}번째 당첨! 🎊")
    if text.startswith(('/', '!')):
        cmd = re.sub(r"^[ /!]+", "", text.split()[0]).strip()
        room = get_room_data(chat_id)
        if room and "local_commands" in room and cmd in room["local_commands"]: await send_custom_output(context, chat_id, room["local_commands"][cmd])
        elif cmd in db_commands: await send_custom_output(context, chat_id, db_commands[cmd])

async def save_logic_with_delay(chat_id, context, m_id, message=None):
    global db_commands, admin_sessions, media_group_cache
    if m_id: await asyncio.sleep(2.5) 
    raw_html = media_group_cache[m_id]["caption_html"] if m_id and m_id in media_group_cache else (message.caption_html if message and message.caption_html else (message.text_html if message else ""))
    if not raw_html: return
    if "/스케줄등록" in raw_html:
        await save_schedule_logic(chat_id, context, m_id, raw_html)
        return
    target_chat_id = admin_sessions.get(ADMIN_ID)
    try:
        if "/이벤트설정" in raw_html: key, content = "_event_celebration_", raw_html.split("/이벤트설정", 1)[1].strip()
        else:
            match = re.search(r"/personal\s+(\S+)\s*(.*)", raw_html, re.IGNORECASE | re.DOTALL)
            if match: key, content = match.group(1), match.group(2)
            else: return
        msg, btn = content.rsplit("---", 1) if "---" in content else (content, "")
        photos = media_group_cache[m_id]["ids"] if m_id and m_id in media_group_cache else []
        cmd_data = {"photos": photos, "caption": msg.strip(), "buttons": re.sub('<[^<]+?>', '', btn).strip()}
        if target_chat_id and target_chat_id != "common":
            col_members.update_one({"chat_id": target_chat_id}, {"$set": {f"local_commands.{key}": cmd_data}})
            await context.bot.send_message(chat_id, f"✅ [{col_members.find_one({'chat_id':target_chat_id})['room_name']}] [{key}] 저장 ({len(photos)}장)")
        else:
            db_commands[key] = cmd_data; save_bot_data(db_commands)
            await context.bot.send_message(chat_id, f"✅ [공용] [{key}] 저장 ({len(photos)}장)")
    except Exception as e: await context.bot.send_message(chat_id, f"⚠️ 오류: {str(e)}")
    if m_id in media_group_cache: del media_group_cache[m_id]

async def save_schedule_logic(chat_id, context, m_id, raw_html):
    target_chat_id = admin_sessions.get(ADMIN_ID)
    if not target_chat_id or target_chat_id == "common": return await context.bot.send_message(chat_id, "⚠️ 방을 먼저 선택하세요.")
    try:
        header, content = raw_html.split("/스케줄등록", 1)[1].strip().split(" ", 1)
        name, start_s, end_s, slot_s, interval_s = header.split("|")
        # KST 적용하여 날짜 파싱 ⭐
        start_dt = datetime.strptime(start_s, "%Y-%m-%d %H:%M").replace(tzinfo=KST)
        end_dt = datetime.strptime(end_s, "%Y-%m-%d %H:%M").replace(tzinfo=KST)
        slot_start, slot_end = slot_s.split("-")
        msg, btn = content.rsplit("---", 1) if "---" in content else (content, "")
        photos = media_group_cache[m_id]["ids"] if m_id and m_id in media_group_cache else []
        sched_data = {
            "chat_id": target_chat_id, "name": name, "start_dt": start_dt, "end_dt": end_dt,
            "slot_start": slot_start, "slot_end": slot_end, "interval": int(interval_s),
            "data": {"photos": photos, "caption": msg.strip(), "buttons": re.sub('<[^<]+?>', '', btn).strip()}
        }
        res = col_sched.insert_one(sched_data)
        context.job_queue.run_repeating(run_scheduled_task, interval=int(interval_s)*60, first=1, data={'id': res.inserted_id}, name=str(res.inserted_id))
        await context.bot.send_message(chat_id, f"⏰ [{name}] 스케줄 예약 완료! ({len(photos)}장)")
    except Exception as e: await context.bot.send_message(chat_id, f"⚠️ 스케줄 오류: {str(e)}")
    if m_id in media_group_cache: del media_group_cache[m_id]

async def send_custom_output(context, chat_id, data, title=""):
    try:
        photos, caption = data.get("photos", []), f"<b>{title}</b>\n\n{data['caption']}" if title else data['caption']
        markup = None
        if data.get("buttons"):
            keyboard = [[InlineKeyboardButton(b.split('|')[0].strip(), url=b.split('|')[1].strip()) for b in line.split('&&') if '|' in b] for line in data["buttons"].split('\n')]
            markup = InlineKeyboardMarkup(keyboard) if any(keyboard) else None
        if not photos: await context.bot.send_message(chat_id, caption, parse_mode="HTML", reply_markup=markup)
        elif len(photos) == 1: await context.bot.send_photo(chat_id, photos[0], caption=caption, parse_mode="HTML", reply_markup=markup)
        else:
            media = [InputMediaPhoto(photos[0], caption=caption, parse_mode="HTML")] + [InputMediaPhoto(f) for f in photos[1:]]
            await context.bot.send_media_group(chat_id, media)
            if markup: await context.bot.send_message(chat_id, "⚡️ 버튼 확인", reply_markup=markup)
    except: pass

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global db_commands, admin_sessions
    query = update.callback_query
    if query.from_user.id != ADMIN_ID: return
    if query.data.startswith("set_room:"):
        r_id = query.data.split(":")[1]; admin_sessions[ADMIN_ID] = r_id
        title = "공용 모드" if r_id == "common" else f"[{col_members.find_one({'chat_id': r_id})['room_name']}] 설정 모드"
        btns = [[InlineKeyboardButton("📋 일반 리스트", callback_data=f"show_list:{r_id}"), InlineKeyboardButton("⏰ 스케줄 리스트", callback_data=f"show_sched:{r_id}")]]
        await query.edit_message_text(f"🎯 **{title}** 활성화", reply_markup=InlineKeyboardMarkup(btns))
    elif query.data.startswith("show_list:"):
        r_id = query.data.split(":")[1]
        if r_id == "common": target, title, prefix = db_commands, "공용", "del_"
        else:
            room = col_members.find_one({"chat_id": r_id}); target, title, prefix = room.get("local_commands", {}), room['room_name'], f"rdel:{r_id}:"
        btns = [[InlineKeyboardButton(f"🗑️ {k}", callback_data=f"{prefix}{k}")] for k in target.keys()]
        btns.append([InlineKeyboardButton("🔙 처음으로", callback_data="back_to_rooms")])
        await query.edit_message_text(f"🛠️ [{title}] 관리:", reply_markup=InlineKeyboardMarkup(btns))
    elif query.data.startswith("show_sched:"):
        r_id = query.data.split(":")[1]; scheds = list(col_sched.find({"chat_id": r_id}))
        btns = [[InlineKeyboardButton(f"🗑️ {s['name']}", callback_data=f"dsched:{s['_id']}")] for s in scheds]
        btns.append([InlineKeyboardButton("🔙 처음으로", callback_data="back_to_rooms")])
        await query.edit_message_text("⏰ 예약 스케줄:", reply_markup=InlineKeyboardMarkup(btns))
    elif query.data.startswith("dsched:"):
        sid = query.data.split(":")[1]; col_sched.delete_one({"_id": ObjectId(sid)})
        for job in context.job_queue.get_jobs_by_name(sid): job.schedule_removal()
        await query.answer("삭제 완료!"); await handle_callback(update, context)
    elif query.data == "back_to_rooms":
        all_rooms = list(col_members.find())
        btns = [[InlineKeyboardButton("📁 [공용] 설정", callback_data="set_room:common")]]
        for r in all_rooms:
            if "room_name" in r: btns.append([InlineKeyboardButton(f"🏠 {r['room_name']} 설정", callback_data=f"set_room:{r['chat_id']}")])
        await query.edit_message_text("📂 방을 선택하세요:", reply_markup=InlineKeyboardMarkup(btns))
    elif query.data.startswith("rdel:"):
        _, r_id, key = query.data.split(":", 2); col_members.update_one({"chat_id": r_id}, {"$unset": {f"local_commands.{key}": ""}})
        await query.answer(f"[{key}] 삭제!"); await handle_callback(update, context)
    elif query.data.startswith("del_"):
        cmd = query.data.replace("del_", ""); del db_commands[cmd]; save_bot_data(db_commands)
        await query.answer(f"[공용] {cmd} 삭제!"); await handle_callback(update, context)

async def post_init(application):
    for s in col_sched.find(): application.job_queue.run_repeating(run_scheduled_task, interval=s['interval']*60, first=5, data={'id': s['_id']}, name=str(s['_id']))

if __name__ == "__main__":
    if TOKEN and MONGO_URL:
        threading.Thread(target=run_flask, daemon=True).start()
        app = ApplicationBuilder().token(TOKEN).post_init(post_init).build()
        app.add_handler(MessageHandler(filters.ALL, handle_message))
        app.add_handler(CallbackQueryHandler(handle_callback))
        app.run_polling()
