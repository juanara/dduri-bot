import os, re, threading, asyncio, logging, random, html, json, requests
from telegram import Update, InputMediaPhoto, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes, CallbackQueryHandler
from flask import Flask
from pymongo import MongoClient

# 1. 로그 및 서버 설정
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

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

# 3. MongoDB 연결 및 데이터 함수
client = MongoClient(MONGO_URL)
mongodb = client['dduri_bot_db']
col_main = mongodb['settings']   # 커스텀 명령어, 카운터
col_members = mongodb['members'] # 채팅방별 멤버 리스트

def load_bot_data():
    data = col_main.find_one({"id": "bot_main_data"})
    if not data: return {"commands": {}, "counter": 0}
    return data

def save_bot_data(commands, counter):
    col_main.update_one(
        {"id": "bot_main_data"},
        {"$set": {"commands": commands, "counter": counter}},
        upsert=True
    )

def save_member(chat_id, user_id, name):
    sid, uid = str(chat_id), str(user_id)
    col_members.update_one(
        {"chat_id": sid},
        {"$set": {f"users.{uid}": name}},
        upsert=True
    )

def get_members(chat_id):
    data = col_members.find_one({"chat_id": str(chat_id)})
    return data.get("users", {}) if data else {}

# 권한 체크 함수 (봇 주인 OR 그룹 관리자) ⭐
async def is_authorized(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid == ADMIN_ID: return True # 봇 주인은 무조건 통과
    if update.effective_chat.type == "private": return False # 개인톡은 본인 외 금지
    
    try:
        member = await context.bot.get_chat_member(update.effective_chat.id, uid)
        return member.status in ["administrator", "creator"] # 관리자나 방장이면 통과
    except:
        return False

# 초기 데이터 동기화
current_data = load_bot_data()
db_commands = current_data.get("commands", {})
message_counter = current_data.get("counter", 0)
media_group_cache = {}

# 4. 실시간 날씨 함수
async def get_realtime_weather(city_input="수원"):
    if not WEATHER_API_KEY: return "❌ WEATHER_API_KEY를 등록해주세요."
    city_map = {"수원": "Suwon", "서울": "Seoul", "인천": "Incheon", "부산": "Busan", "제주": "Jeju"}
    city_name = city_map.get(city_input, city_input)
    try:
        url = f"http://api.openweathermap.org/data/2.5/weather?q={city_name}&appid={WEATHER_API_KEY}&units=metric&lang=kr"
        data = requests.get(url, timeout=5).json()
        if data.get("cod") == 200:
            desc, temp, feels, icon = data["weather"][0]["description"], data["main"]["temp"], data["main"]["feels_like"], data["weather"][0]["icon"]
            emoji = "☀️" if "01" in icon else "☁️" if "02" in icon or "03" in icon or "04" in icon else "🌧️"
            return f"📍 <b>{city_input} 실시간 날씨</b> {emoji}\n\n🌡️ <b>현재:</b> {temp}°C\n🤔 <b>체감:</b> {feels}°C\n📝 <b>상태:</b> {desc}"
        return "❌ 지역을 찾을 수 없습니다."
    except: return "⚠️ 날씨 서버 오류"

# 5. 메뉴 추천 로직
def get_menu_recommendation(command):
    morning = ["전복죽", "계란 토스트", "시리얼", "에그 베네딕트", "그릭 요거트", "베이글", "브런치"]
    dinner = ["삼겹살", "치킨", "피자", "모듬 회", "소곱창", "불족발", "스테이크", "낙곱새"]
    coffee = ["아메리카노", "라떼", "돌체 라떼", "자바 칩 프라푸치노", "쿨 라임 피지오", "허니 자몽 블랙 티"]
    snack = ["떡볶이", "핫도그", "크로플", "츄러스", "뚱카롱", "붕어빵", "호떡", "소떡소떡"]
    
    if "/아메추" in command: res, cat = random.choice(morning), "아침 ☀️"
    elif "/저메추" in command: res, cat = random.choice(dinner), "저녁 🌙"
    elif "/커추" in command: res, cat = random.choice(coffee), "스타벅스 ☕"
    elif "/간추" in command: res, cat = random.choice(snack), "간식 🥨"
    else: res, cat = random.choice(["제육볶음", "돈까스", "짜장면", "쌀국수", "텐동", "초밥"]), "점심 🍴"
    return f"🍴 <b>{cat} 추천</b>\n\n추천 메뉴: <b>{res}</b>\n\n💬 <i>가보자고!</i>"

# 6. 주사위 가중치
def get_weighted_dice():
    seed = random.random() * 100
    if seed < 0.1: return random.randrange(40000, 50001, 500)
    elif seed < 1.1: return random.randrange(30000, 40000, 500)
    elif seed < 4.1: return random.randrange(10000, 30000, 500)
    elif seed < 8.1: return random.randrange(5000, 10000, 500)
    else: return random.randrange(500, 5000, 500)

async def delete_messages_later(context, chat_id, message_ids, delay):
    await asyncio.sleep(delay)
    for msg_id in message_ids:
        try: await context.bot.delete_message(chat_id=chat_id, message_id=msg_id)
        except: pass 

# 7. 메인 메시지 핸들러
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global db_commands, message_counter, media_group_cache
    if not update.message: return
    
    uid, text = update.message.from_user.id, update.message.text or ""
    text_lower = text.lower() # 대소문자 무시용
    cap_html, chat_id = update.message.caption_html or "", update.effective_chat.id
    name = html.escape(update.message.from_user.first_name)
    is_private = update.effective_chat.type == "private"

    # [수집] 채팅 치는 사람 영구 등록
    if not is_private and not update.message.from_user.is_bot:
        save_member(chat_id, uid, name)

    # [수집] 사용자님이 태그한 사람 강제 낚시 등록
    if update.message.entities:
        for entity in update.message.entities:
            if entity.type == "text_mention":
                target = entity.user
                save_member(chat_id, target.id, html.escape(target.first_name))

    if not update.message.from_user.is_bot:
        # 권한 확인 (주인 또는 관리자) ⭐
        is_auth = await is_authorized(update, context)

        if is_auth:
            # 전체 멘션 (10인 분할)
            if text_lower.startswith(("/all", "/전체공지", "/전체멘션")):
                members = get_members(chat_id)
                if not members:
                    return await update.message.reply_text("❌ 등록 멤버 없음 (@로 이름을 선택해 등록하세요!)")
                
                m_list = list(members.items())
                for i in range(0, len(m_list), 10):
                    chunk = m_list[i:i+10]
                    mentions = [f"<a href='tg://user?id={mid}'>{mname}</a>" for mid, mname in chunk]
                    await context.bot.send_message(chat_id, f"📢 <b>전체 소집 ({i//10 + 1}팀)</b>\n" + " ".join(mentions), parse_mode="HTML")
                    await asyncio.sleep(0.5)
                return

            # 리스트 명부 확인
            if text_lower == "/리스트":
                members = get_members(chat_id)
                if not members: 
                    return await update.message.reply_text(f"📉 이 방({chat_id})은 아직 수집된 데이터가 없습니다.")
                body = "\n".join([f"{i+1}. {mname} (<code>{mid}</code>)" for i, (mid, mname) in enumerate(members.items())])
                return await update.message.reply_text(f"📋 <b>현재 방 등록 멤버 (총 {len(members)}명)</b>\n\n{body}", parse_mode="HTML")

        # 하우돈 검거 (2.5초 삭제)
        if any(w in text for w in ["니노", "노무현", "무현", "노무"]):
            rep = await update.message.reply_text(f"<tg-spoiler>하우돈 검거 완료 👮‍♂️</tg-spoiler>", parse_mode="HTML")
            s_msg = None
            if os.path.exists("2.webm"):
                with open("2.webm", "rb") as f: s_msg = await context.bot.send_sticker(chat_id, f)
            asyncio.create_task(delete_messages_later(context, chat_id, [update.message.message_id, rep.message_id, (s_msg.message_id if s_msg else None)], 2.5))
            return 

        # 분부니/뷰니 찬양 (3초 삭제)
        s_count = text.count('ㅅ')
        if ("분부니" in text and s_count >= 6) or ("뷰니" in text and s_count >= 5):
            rep = await update.message.reply_text("대여왕 강림!!! 👑 ㅅㅅㅅㅅ", parse_mode="HTML")
            s_msg, a_msg = None, None
            if os.path.exists("1.webm"):
                with open("1.webm", "rb") as f: s_msg = await context.bot.send_sticker(chat_id, f)
            if os.path.exists("1.ogg"):
                with open("1.ogg", "rb") as f: a_msg = await context.bot.send_voice(chat_id, f)
            asyncio.create_task(delete_messages_later(context, chat_id, [update.message.message_id, rep.message_id, (s_msg.message_id if s_msg else None), (a_msg.message_id if a_msg else None)], 3.0))
            return

        # ㅅ 가속/무욱자
        elif "무욱자" in text and s_count >= 4:
            return await update.message.reply_text("우욱자갓 ㅅㅅㅅㅅ 미친 폼!! 🔥")
        elif s_count >= 9 or text.count('ㅆ') >= 9:
            return await update.message.reply_text("개나이스! 앙 기모링~~ 🔥")

    # 메뉴/날씨 추천 (5초 삭제)
    if any(text_lower.startswith(c) for c in ["/아메추", "/점메추", "/저메추", "/커추", "/간추", "/날씨"]):
        res = await get_realtime_weather(text.split()[1]) if text_lower.startswith("/날씨") and len(text.split()) > 1 else (await get_realtime_weather("수원") if text_lower.startswith("/날씨") else get_menu_recommendation(text_lower))
        rep = await update.message.reply_text(res, parse_mode="HTML")
        asyncio.create_task(delete_messages_later(context, chat_id, [update.message.message_id, rep.message_id], 5.0))
        return

    # 주사위
    if text in ["/주사위", "!주사위"]:
        res = get_weighted_dice()
        icon = "💎" if res >= 40000 else "🔥" if res >= 10000 else "🎲"
        return await update.message.reply_text(f"<b>{name}</b>님의 결과: {icon} <b>{res:,}</b>", parse_mode="HTML")

    # 관리자 전용 등록 기능 (개인 DM)
    if uid == ADMIN_ID and is_private:
        if text == "/카운트확인": return await update.message.reply_text(f"📊 카운트: {message_counter}")
        if update.message.photo:
            m_id = update.message.media_group_id or f"s_{update.message.message_id}"
            if m_id not in media_group_cache: media_group_cache[m_id] = {"ids": [], "caption": "", "task": None}
            media_group_cache[m_id]["ids"].append(update.message.photo[-1].file_id)
            if "/personal" in cap_html.lower() or "/이벤트설정" in cap_html: media_group_cache[m_id]["caption"] = cap_html
            if media_group_cache[m_id]["task"]: media_group_cache[m_id]["task"].cancel()
            media_group_cache[m_id]["task"] = asyncio.create_task(save_logic(m_id, chat_id, context))
            return

    # 카운팅
    if not is_private and not text.startswith(('/', '!')) and not cap_html.startswith('/'):
        message_counter += 1
        if message_counter % 50 == 0: save_bot_data(db_commands, message_counter)

    # 사용자 명령어
    if text.startswith(('/', '!')):
        cmd = re.sub(r"^[ /!]+", "", text.split()[0]).strip()
        if cmd in db_commands: await send_custom_output(context, chat_id, db_commands[cmd])

async def save_logic(m_id, chat_id, context):
    global db_commands, message_counter
    await asyncio.sleep(2.5)
    if m_id in media_group_cache:
        target, raw_cap = media_group_cache[m_id], media_group_cache[m_id]["caption"]
        try:
            match = re.search(r"/personal\s+(\S+)\s*(.*)", raw_cap, re.IGNORECASE | re.DOTALL)
            if match: key, content = match.group(1), match.group(2)
            else: return
            msg, btn = content, ""
            if "---" in content: msg, btn = content.rsplit("---", 1)
            db_commands[key] = {"photos": target["ids"], "caption": msg.strip(), "buttons": re.sub('<[^<]+?>', '', btn).strip()}
            save_bot_data(db_commands, message_counter)
            await context.bot.send_message(chat_id, f"✅ [{key}] 영구 등록 완료")
        except: pass
        del media_group_cache[m_id]

async def send_custom_output(context, chat_id, data, title=""):
    try:
        photos, caption = data["photos"], f"<b>{title}</b>\n\n{data['caption']}" if title else data['caption']
        if len(photos) == 1: await context.bot.send_photo(chat_id, photos[0], caption=caption, parse_mode="HTML")
        else:
            media = [InputMediaPhoto(photos[0], caption=caption, parse_mode="HTML")] + [InputMediaPhoto(fid) for fid in photos[1:]]
            await context.bot.send_media_group(chat_id, media)
    except: pass

if __name__ == "__main__":
    if TOKEN and MONGO_URL:
        threading.Thread(target=run_flask, daemon=True).start()
        app = ApplicationBuilder().token(TOKEN).build()
        app.add_handler(MessageHandler(filters.ALL, handle_message))
        app.run_polling()
