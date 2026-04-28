import os, re, threading, asyncio, logging, random, html, json, requests
from datetime import datetime, timedelta, timezone
from telegram import Update, InputMediaPhoto, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes, CallbackQueryHandler
from flask import Flask
from pymongo import MongoClient
from bson.objectid import ObjectId

# 1. 로그 및 서버 설정
logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)
KST = timezone(timedelta(hours=9))

flask_app = Flask(__name__)
@flask_app.route('/')
def health_check(): return "Bot is running!", 200

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    flask_app.run(host='0.0.0.0', port=port)

# 2. 환경 변수 및 DB 연결
TOKEN = os.getenv("TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "8472713103"))
WEATHER_API_KEY = os.getenv("WEATHER_API_KEY")
MONGO_URL = os.getenv("MONGO_URL")

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

# [자체 엔진] 스케줄러 (무삭제 보존 ⭐)
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

# [권한 체크] (무삭제 보존 ⭐)
async def is_authorized(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid == ADMIN_ID: return True
    if update.effective_chat.type == "private": return False
    try:
        member = await context.bot.get_chat_member(update.effective_chat.id, uid)
        return member.status in ["administrator", "creator"]
    except: return False

# [날씨/메뉴 로직] (무삭제 보존 ⭐)
async def get_realtime_weather(city_input="수원"):
    if not WEATHER_API_KEY: return "❌ API_KEY 누락"
    city_map = {"수원": "Suwon", "서울": "Seoul", "인천": "Incheon", "부산": "Busan", "제주": "Jeju"}
    url = f"http://api.openweathermap.org/data/2.5/weather?q={city_map.get(city_input, city_input)}&appid={WEATHER_API_KEY}&units=metric&lang=kr"
    try:
        data = requests.get(url, timeout=5).json()
        if data.get("cod") == 200: return f"📍 <b>{city_input} 날씨</b>\n🌡️ {data['main']['temp']}°C / {data['weather'][0]['description']}"
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

# [메인 핸들러] (선배님의 모든 로직 통합 ⭐)
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

    # [1. 수집 및 통계 / 5000타점 당첨 로직] (복구 ⭐)
    if not is_private and not update.message.from_user.is_bot:
        res = col_members.find_one_and_update(
            {"chat_id": str(chat_id)},
            {"$set": {"room_name": chat_title, f"users.{uid}": name}, "$inc": {"msg_count": 1}},
            upsert=True, return_document=True
        )
        if res and res.get("msg_count", 0) % 5000 == 0:
            evt = res.get("local_commands", {}).get("_event_celebration_") or load_bot_data().get("commands", {}).get("_event_celebration_")
            if evt: await send_custom_output(context.bot, chat_id, evt, f"🎊 {chat_title} {res['msg_count']}번째 당첨! 🎊")

    if not update.message.from_user.is_bot:
        # [2. 하우돈 필터] (38개 완벽 복구 ⭐)
        bad_words = ["일베", "벌레", "노무", "무현", "노무현", "노무쿤", "무현쿤", "노지금무라현노", "지금무라현노", "무라현노", "운지", "운q지", "무q현", "니q노", "니노", "부엉", "부엉이바위", "봉하마을", "봉하", "섹스", "스섹", "쎅", "빨통", "섹q스", "스q섹", "응디", "응q디", "응디시티", "엠씨무현", "mc무현", "엠씨현무", "mc현무", "엠q씨현q무", "노알라", "슨상님", "홍어", "통구이", "중력"]
        if any(w in text_lower for w in bad_words) or any(w in clean_text for w in bad_words):
            rep = await update.message.reply_text(f"<tg-spoiler>하우돈 검거 👮‍♂️</tg-spoiler>", parse_mode="HTML")
            sticker_id = None
            if os.path.exists("2.webm"):
                try: 
                    with open("2.webm", "rb") as f: s_msg = await context.bot.send_sticker(chat_id, f); sticker_id = s_msg.message_id
                except: pass
            asyncio.create_task(delete_messages_later(context, chat_id, [update.message.message_id, rep.message_id, sticker_id], 10.0))
            return 

        # [3. ㅅ 리액션] (무삭제 보존 ⭐)
        s_count = text.count('ㅅ')
        if ("분부니" in text and s_count >= 6) or ("뷰니" in text and s_count >= 5):
            rep = await update.message.reply_text("대여왕 강림!!! 👑 ㅅㅅㅅㅅ", parse_mode="HTML")
            asyncio.create_task(delete_messages_later(context, chat_id, [update.message.message_id, rep.message_id], 10.0))
            return
        elif "무욱자" in text and s_count >= 4:
            await update.message.reply_text("우욱자갓 ㅅㅅㅅㅅ 미친 폼!! 🔥")
            return
        elif s_count >= 9 or text.count('ㅆ') >= 9:
            accel = ["폼 미쳤다ㄷㄷ 오늘 텐션 개오짐!! 🔥", "완전 럭키비키잖아!! ✨", "이거지ㅋㅋ 분위기 찢었다!! 🚀", "도파민 폭발함!! 🧨", "갓벽하다 진짜ㅋㅋ 💎"]
            await update.message.reply_text(random.choice(accel))
            return

    # [4. 날씨/메뉴/주사위/멘션] (무삭제 보존 ⭐)
    if any(text_lower.startswith(c) for c in ["/아메추", "/점메추", "/저메추", "/커추", "/간추", "/날씨"]):
        res = await get_realtime_weather(text.split()[1]) if text_lower.startswith("/날씨") and len(text.split()) > 1 else (await get_realtime_weather("수원") if text_lower.startswith("/날씨") else get_menu_recommendation(text_lower))
        rep = await update.message.reply_text(res, parse_mode="HTML")
        asyncio.create_task(delete_messages_later(context, chat_id, [update.message.message_id, rep.message_id], 10.0))
        return
    if text in ["/주사위", "!주사위"]:
        r = random.randrange(500, 50001, 500); icon = "💎" if r >= 40000 else "🔥" if r >= 10000 else "🎲"
        rep = await update.message.reply_text(f"<b>{name}</b>님의 결과: {icon} <b>{r:,}</b>", parse_mode="HTML")
        asyncio.create_task(delete_messages_later(context, chat_id, [update.message.message_id, rep.message_id], 15.0))
        return
    
    # 전체 멘션 (복구 ⭐)
    if (await is_authorized(update, context)) and text_lower.startswith(("/all", "/전체공지", "/전체멘션")):
        room = col_members.find_one({"chat_id": str(chat_id)}); members = room.get("users", {}) if room else {}
        if not members: return await update.message.reply_text("❌ 멤버 없음")
        m_list = list(members.items())
        for i in range(0, len(m_list), 10):
            mentions = [f"<a href='tg://user?id={mid}'>{mname}</a>" for mid, mname in m_list[i:i+10]]
            await context.bot.send_message(chat_id, " ".join(mentions), parse_mode="HTML")
            await asyncio.sleep(0.5)
        return

    # [5. 관리자 전용 UI / 스케줄/Personal 저장] (무삭제 보존 ⭐)
    if uid == ADMIN_ID and is_private:
        if text.startswith(('/설정', '/리스트', '/삭제', '/스케줄')):
            btns = [[InlineKeyboardButton("📁 [공용] 설정", callback_data="set_room:common")]]
            for r in list(col_members.find()):
                if "room_name" in r: btns.append([InlineKeyboardButton(f"🏠 {r['room_name']}", callback_data=f"set_room:{r['chat_id']}")])
            return await update.message.reply_text("📂 관리할 방 선택:", reply_markup=InlineKeyboardMarkup(btns))
        if text_lower == "/카운트확인":
            all_r = list(col_members.find()); summary = [f"🏠 <b>{r.get('room_name','?')}</b>: {r.get('msg_count',0):,}회" for r in all_r]
            return await update.message.reply_text("📊 <b>전체 통계</b>\n\n" + "\n".join(summary or ["데이터 없음"]), parse_mode="HTML")

        if update.message.photo or any(x in (text+cap_html).lower() for x in ["/personal", "/이벤트설정", "/스케줄등록"]):
            m_id = update.message.media_group_id or f"s_{update.message.message_id}"
            if update.message.photo:
                if m_id not in media_group_cache: media_group_cache[m_id] = {"ids": [], "caption": update.message.caption_html or "", "task": None}
                media_group_cache[m_id]["ids"].append(update.message.photo[-1].file_id)
                if media_group_cache[m_id]["task"]: media_group_cache[m_id]["task"].cancel()
                media_group_cache[m_id]["task"] = asyncio.create_task(save_logic_with_delay(chat_id, context, m_id))
            else: await save_logic_with_delay(chat_id, context, None, update.message)
            return

    # [6. 명령어 호출] (무삭제 보존 ⭐)
    if text.startswith(('/', '!')):
        cmd = re.sub(r"^[ /!]+", "", text.split()[0]).strip()
        room = col_members.find_one({"chat_id": str(chat_id)})
        target = room.get("local_commands", {}).get(cmd) if room else None
        if target: await send_custom_output(context.bot, chat_id, target)
        elif cmd in load_bot_data().get("commands", {}): await send_custom_output(context.bot, chat_id, load_bot_data()["commands"][cmd])

# [저장 로직 통합] (3.5초 대기 & 무삭제 저장 ⭐)
async def save_logic_with_delay(chat_id, context, m_id, message=None):
    if m_id: await asyncio.sleep(3.5)
    raw_html = media_group_cache[m_id]["caption"] if m_id else (message.caption_html or message.text_html or "")
    if not raw_html: return
    target_chat_id = get_admin_session(ADMIN_ID)
    if not target_chat_id: return await context.bot.send_message(chat_id, "⚠️ 방을 먼저 선택하세요.")

    try:
        if "/스케줄등록" in raw_html:
            core = raw_html.split("/스케줄등록", 1)[1].strip(); h = [p.strip() for p in core.split("|", 4)]
            intv, content = h[4].split(None, 1); photos = media_group_cache[m_id]["ids"] if m_id else []
            data = {"chat_id": target_chat_id, "name": h[0], "start_dt": h[1], "end_dt": h[2], "slot_start": h[3].replace("-","").strip()[:4], "slot_end": h[3].replace("-","").strip()[-4:], "interval": int(intv), "data": {"photos": photos, "caption": content.strip()}}
            res = col_sched.insert_one(data); last_run_cache[str(res.inserted_id)] = datetime.now(KST) - timedelta(minutes=int(intv))
            await context.bot.send_message(chat_id, f"⏰ [{h[0]}] 예약 완료! (사진 {len(photos)}장)")
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

# [출력 엔진] (무삭제 보존 ⭐)
async def send_custom_output(bot, chat_id, data, title=""):
    try:
        photos, caption, cid = data.get("photos", []), (f"<b>{title}</b>\n\n{data['caption']}" if title else data['caption']), str(chat_id)
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

# [콜백 핸들러] (삭제 UI 로직 포함 ⭐)
async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; data = query.data
    if query.from_user.id != ADMIN_ID: return
    if data.startswith("set_room:"):
        r_id = data.split(":")[1]; set_admin_session(ADMIN_ID, r_id)
        room = col_members.find_one({"chat_id": r_id}); title = f"[{room['room_name']}]" if room else "[공용]"
        btns = [[InlineKeyboardButton("📋 일반 리스트", callback_data=f"show_list:{r_id}"), InlineKeyboardButton("⏰ 스케줄 리스트", callback_data=f"show_sched:{r_id}")]]
        await query.edit_message_text(f"🎯 {title} 설정 활성화!", reply_markup=InlineKeyboardMarkup(btns))
    elif data.startswith("show_list:"):
        r_id = data.split(":")[1]
        target = load_bot_data().get("commands", {}) if r_id == "common" else (col_members.find_one({"chat_id": r_id}).get("local_commands", {}) if col_members.find_one({"chat_id": r_id}) else {})
        btns = [[InlineKeyboardButton(f"🗑 {k}", callback_data=f"del:{r_id}:{k}")] for k in target.keys()]
        btns.append([InlineKeyboardButton("🔙 처음으로", callback_data="back_to_rooms")]); await query.edit_message_text("🗑 삭제할 명령어를 선택하세요:", reply_markup=InlineKeyboardMarkup(btns))
    elif data.startswith("show_sched:"):
        r_id = data.split(":")[1]; scheds = list(col_sched.find({"chat_id": r_id}))
        btns = [[InlineKeyboardButton(f"🗑 {s['name']}", callback_data=f"dsched:{s['_id']}")] for s in scheds]
        btns.append([InlineKeyboardButton("🔙 처음으로", callback_data="back_to_rooms")]); await query.edit_message_text("⏰ 예약 스케줄 목록:", reply_markup=InlineKeyboardMarkup(btns))
    elif data.startswith("del:"):
        _, r_id, key = data.split(":", 2)
        if r_id == "common": cmds = load_bot_data().get("commands", {}); cmds.pop(key, None); save_bot_data(cmds)
        else: col_members.update_one({"chat_id": r_id}, {"$unset": {f"local_commands.{key}": ""}})
        await query.answer(f"[{key}] 삭제 완료!"); await handle_callback(update, context)
    elif data.startswith("dsched:"):
        sid = data.split(":")[1]; col_sched.delete_one({"_id": ObjectId(sid)})
        if sid in last_run_cache: del last_run_cache[sid]
        await query.answer("스케줄 삭제 완료!"); await handle_callback(update, context)
    elif data == "back_to_rooms":
        btns = [[InlineKeyboardButton("📁 [공용] 설정", callback_data="set_room:common")]]
        for r in list(col_members.find()):
            if "room_name" in r: btns.append([InlineKeyboardButton(f"🏠 {r['room_name']}", callback_data=f"set_room:{r['chat_id']}")])
        await query.edit_message_text("📂 방을 선택하세요:", reply_markup=InlineKeyboardMarkup(btns))

async def post_init(application):
    asyncio.create_task(custom_scheduler_loop(application))

if __name__ == "__main__":
    if TOKEN and MONGO_URL:
        threading.Thread(target=run_flask, daemon=True).start()
        app = ApplicationBuilder().token(TOKEN).post_init(post_init).build()
        app.add_handler(MessageHandler(filters.ALL, handle_message))
        app.add_handler(CallbackQueryHandler(handle_callback))
        app.run_polling()
