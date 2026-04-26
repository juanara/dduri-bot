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
col_main = mongodb['settings']
col_members = mongodb['members']

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

def save_member(chat_id, user_id, name, chat_title):
    sid, uid = str(chat_id), str(user_id)
    col_members.update_one(
        {"chat_id": sid},
        {"$set": {f"users.{uid}": name, "room_name": chat_title}},
        upsert=True
    )

def get_members(chat_id):
    data = col_members.find_one({"chat_id": str(chat_id)})
    return data.get("users", {}) if data else {}

# 권한 체크 함수
async def is_authorized(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid == ADMIN_ID: return True
    if update.effective_chat.type == "private": return False
    try:
        member = await context.bot.get_chat_member(update.effective_chat.id, uid)
        return member.status in ["administrator", "creator"]
    except: return False

# 초기 데이터 동기화
current_data = load_bot_data()
db_commands = current_data.get("commands", {})
message_counter = current_data.get("counter", 0)
media_group_cache = {}

# 4. 실시간 날씨 함수 (한글 도시명 지원)
async def get_realtime_weather(city_input="수원"):
    if not WEATHER_API_KEY: return "❌ API_KEY 누락"
    city_map = {
        "수원": "Suwon", "서울": "Seoul", "인천": "Incheon", "부산": "Busan", 
        "대전": "Daejeon", "광주": "Gwangju", "대구": "Daegu", "울산": "Ulsan",
        "제주": "Jeju", "안양": "Anyang", "성남": "Seongnam", "고양": "Goyang",
        "용인": "Yongin", "청주": "Cheongju", "천안": "Cheonan", "전주": "Jeonju"
    }
    city_name = city_map.get(city_input, city_input)
    url = f"http://api.openweathermap.org/data/2.5/weather?q={city_name}&appid={WEATHER_API_KEY}&units=metric&lang=kr"
    try:
        data = requests.get(url, timeout=5).json()
        if data.get("cod") == 200:
            return f"📍 <b>{city_input} 날씨</b>\n🌡️ {data['main']['temp']}°C / {data['weather'][0]['description']}"
        return f"❌ '{city_input}' 지역 찾기 실패"
    except: return "⚠️ 오류"

# 5. 메뉴 추천 로직 (스타벅스 Top 30 & 아/점/저 30선)
def get_menu_recommendation(command):
    starbucks_30 = [
        "아이스 아메리카노", "카페 라떼", "자몽 허니 블랙 티", "돌체 라떼", "콜드 브루",
        "바닐라 크림 콜드 브루", "자바 칩 프라푸치노", "쿨 라임 피지오", "화이트 초콜릿 모카", "카라멜 마키아또",
        "제주 유기농 말차 라떼", "민트 초콜릿 칩 블렌디드", "더블 에스프레소 칩 프라푸치노", "에스프레소 프라푸치노", "바닐라 플랫 화이트",
        "카페 모카", "카푸치노", "얼 그레이 티 라떼", "블랙 티 레모네이드 피지오", "핑크 드링크 위드 딸기 아사이",
        "딸기 아사이 레모네이드", "망고 패션 티 블렌디드", "유자 패션 피지오", "돌체 블랙 밀크 티", "차이 티 라떼",
        "블론드 바닐라 더블 샷 마키아또", "클래식 밀크 티", "피스타치오 크림 콜드 브루", "오늘의 커피", "바닐라 더블 샷"
    ]
    breakfast_30 = [
        "토스트", "북어국", "맥모닝", "전복죽", "시리얼", "에그드랍", "샌드위치", "사과와 요거트", "누룽지", "김밥",
        "프렌치 토스트", "콩나물국밥", "바나나", "베이글", "순두부찌개", "단호박죽", "샐러드", "소고기무국", "주먹밥", "미역국",
        "잉글리쉬 머핀", "시금치된장국", "가래떡 구이", "찐고구마", "스크램블 에그", "감자스프", "블루베리 베이글", "누드김밥", "누룽지탕", "떡국"
    ]
    lunch_30 = [
        "김치찌개", "된장찌개", "비빔밥", "돈까스", "짜장면", "짬뽕", "제육볶음", "육개장", "칼국수", "수제비",
        "냉면", "쌀국수", "파스타", "규동", "가츠동", "회덮밥", "부대찌개", "뚝배기불고기", "함박스테이크", "오므라이스",
        "잔치국수", "텐동", "라멘", "마라탕", "떡볶이", "버거킹", "포케", "초밥", "카레", "고등어구이"
    ]
    dinner_30 = [
        "삼겹살", "치킨", "소곱창", "족발", "보쌈", "소갈비", "회", "매운탕", "아구찜", "감자탕",
        "샤브샤브", "양꼬치", "피자", "스테이크", "파스타", "닭갈비", "곱창전골", "조개구이", "해물찜", "찜닭",
        "낙지볶음", "쪽갈비", "양념게장", "보리굴비", "월남쌈", "닭발", "파전과 막걸리", "골뱅이무침", "소고기등심", "대게찜"
    ]
    if "/커추" in command: return f"☕️ <b>스타벅스 Top 30 추천</b>: <b>{random.choice(starbucks_30)}</b>"
    elif "/아메추" in command: return f"🌅 <b>오늘의 아침 추천</b>: <b>{random.choice(breakfast_30)}</b>"
    elif "/점메추" in command: return f"🍴 <b>오늘의 점심 추천</b>: <b>{random.choice(lunch_30)}</b>"
    elif "/저메추" in command: return f"🍻 <b>오늘의 저녁 추천</b>: <b>{random.choice(dinner_30)}</b>"
    else: return f"🍴 <b>추천 메뉴</b>: <b>{random.choice(lunch_30)}</b>"

# 6. 주사위 가중치
def get_weighted_dice():
    seed = random.random() * 100
    if seed < 0.1: return random.randrange(40000, 50001, 500)
    elif seed < 1.1: return random.randrange(30000, 40000, 500)
    elif seed < 8.1: return random.randrange(5000, 10000, 500)
    else: return random.randrange(500, 5000, 500)

async def delete_messages_later(context, chat_id, message_ids, delay):
    await asyncio.sleep(delay)
    for msg_id in message_ids:
        if msg_id:
            try: await context.bot.delete_message(chat_id=chat_id, message_id=msg_id)
            except: pass 

# 7. 메인 메시지 핸들러
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global db_commands, message_counter, media_group_cache
    if not update.message: return
    
    uid, text = update.message.from_user.id, update.message.text or ""
    text_lower = text.lower()
    cap_html, chat_id = update.message.caption_html or "", update.effective_chat.id
    chat_title = update.effective_chat.title or "개인 대화"
    name = html.escape(update.message.from_user.first_name)
    is_private = update.effective_chat.type == "private"

    if not is_private and not update.message.from_user.is_bot:
        save_member(chat_id, uid, name, chat_title)
    if update.message.entities:
        for entity in update.message.entities:
            if entity.type == "text_mention": save_member(chat_id, entity.user.id, html.escape(entity.user.first_name), chat_title)

    if not is_private and not text.startswith(('/', '!')) and not cap_html.startswith('/') and not update.message.from_user.is_bot:
        message_counter += 1
        if message_counter % 20 == 0: save_bot_data(db_commands, message_counter)

    if not update.message.from_user.is_bot:
        is_auth = await is_authorized(update, context)

        if is_auth:
            if text_lower == "/카운트확인": return await update.message.reply_text(f"📊 현재 누적 카운트: <b>{message_counter:,}</b>", parse_mode="HTML")
            if text_lower.startswith(("/all", "/전체공지", "/전체멘션")):
                members = get_members(chat_id)
                if not members: return await update.message.reply_text("❌ 등록 멤버 없음")
                m_list = list(members.items())
                for i in range(0, len(m_list), 10):
                    chunk = m_list[i:i+10]
                    mentions = [f"<a href='tg://user?id={mid}'>{mname}</a>" for mid, mname in chunk]
                    await context.bot.send_message(chat_id, " ".join(mentions), parse_mode="HTML")
                    await asyncio.sleep(0.5)
                return
            if text_lower == "/리스트":
                all_rooms = col_members.find() if is_private else [col_members.find_one({"chat_id": str(chat_id)})]
                summary = [f"🏠 <b>{r.get('room_name','?')}</b>\n인원: {len(r.get('users',{}))}명\n" for r in all_rooms if r]
                if not summary: return await update.message.reply_text("📉 데이터 없음")
                return await update.message.reply_text("📋 <b>소통 VIP 회원수</b>\n\n" + "\n".join(summary), parse_mode="HTML")

        # [필터링] 하우돈 검거 (2.5초 삭제)
        bad_words = ["니노", "노무현", "무현", "노무", "운지", "운q지", "무q현", "니q노", "부엉", "부엉이바위", "봉하마을", "봉하", "섹스", "스섹", "쎅", "빨통", "섹q스", "스q섹"]
        if any(w in text for w in bad_words):
            rep = await update.message.reply_text(f"<tg-spoiler>하우돈 검거 👮‍♂️</tg-spoiler>", parse_mode="HTML")
            s_msg = None
            if os.path.exists("2.webm"):
                try:
                    with open("2.webm", "rb") as f: s_msg = await context.bot.send_sticker(chat_id, f)
                except: pass
            asyncio.create_task(delete_messages_later(context, chat_id, [update.message.message_id, rep.message_id, (s_msg.message_id if s_msg else None)], 2.5))
            return 

        # [리액션] 여왕님 찬양 (3초 삭제)
        s_count = text.count('ㅅ')
        if ("분부니" in text and s_count >= 6) or ("뷰니" in text and s_count >= 5):
            queen_mentions = ["대여왕 강림!!! 👑 ㅅㅅㅅㅅ", "여왕님 폼 미쳤다!! 🙇‍♂️ 충성충성", "역시 우리 여왕님 클라스!! 👸", "세상을 지배하는 뷰모!! 👑 찬양하라!!"]
            rep = await update.message.reply_text(random.choice(queen_mentions), parse_mode="HTML")
            s_msg, a_msg = None, None
            if os.path.exists("1.webm"):
                try:
                    with open("1.webm", "rb") as f: s_msg = await context.bot.send_sticker(chat_id, f)
                except: pass
            if os.path.exists("1.ogg"):
                try:
                    with open("1.ogg", "rb") as f: a_msg = await context.bot.send_voice(chat_id, f)
                except: pass
            asyncio.create_task(delete_messages_later(context, chat_id, [update.message.message_id, rep.message_id, (s_msg.message_id if s_msg else None), (a_msg.message_id if a_msg else None)], 3.0))
            return

        # [리액션] MZ 스타일 가속 멘트 (수정 완료 ⭐)
        elif s_count >= 9 or text.count('ㅆ') >= 9:
            accel_mentions = [
                "개나이스! 앙 기모링~~ 🔥",
                "폼 미쳤다ㄷㄷ 오늘 텐션 개오짐!! 🔥",
                "완전 럭키비키잖아!! 오늘 되는 날임? ✨",
                "이거지ㅋㅋ 분위기 찢었다!! 가즈아아아아!! 🚀",
                "텐션 실화냐? 오늘 도파민 폭발함!! 🧨",
                "갓벽하다 진짜ㅋㅋ 분위기 무엇? 미쳤다ㄷㄷ 💎"
            ]
            return await update.message.reply_text(random.choice(accel_mentions))

    # 메뉴/날씨 추천 (5초 삭제)
    if any(text_lower.startswith(c) for c in ["/아메추", "/점메추", "/저메추", "/커추", "/간추", "/날씨"]):
        res = await get_realtime_weather(text.split()[1]) if text_lower.startswith("/날씨") and len(text.split()) > 1 else (await get_realtime_weather("수원") if text_lower.startswith("/날씨") else get_menu_recommendation(text_lower))
        rep = await update.message.reply_text(res, parse_mode="HTML")
        asyncio.create_task(delete_messages_later(context, chat_id, [update.message.message_id, rep.message_id], 5.0))
        return

    # 주사위 (10초 삭제)
    if text in ["/주사위", "!주사위"]:
        res = get_weighted_dice()
        icon = "💎" if res >= 40000 else "🔥" if res >= 10000 else "🎲"
        rep = await update.message.reply_text(f"<b>{name}</b>님의 결과: {icon} <b>{res:,}</b>", parse_mode="HTML")
        asyncio.create_task(delete_messages_later(context, chat_id, [update.message.message_id, rep.message_id], 10.0))
        return

    # 관리자 전용 DM 기능
    if uid == ADMIN_ID and is_private:
        if text == "/카운트리로드":
            message_counter = 0
            save_bot_data(db_commands, message_counter)
            return await update.message.reply_text("🔢 초기화 완료")
        if text in ["/리스트확인", "/삭제"]:
            btns = [[InlineKeyboardButton(f"🗑️ {k} 삭제", callback_data=f"del_{k}")] for k in db_commands.keys()]
            return await update.message.reply_text("📋 삭제 리스트:", reply_markup=InlineKeyboardMarkup(btns))
        if update.message.photo:
            m_id = update.message.media_group_id or f"s_{update.message.message_id}"
            if m_id not in media_group_cache: media_group_cache[m_id] = {"ids": [], "caption": "", "task": None}
            media_group_cache[m_id]["ids"].append(update.message.photo[-1].file_id)
            if "/personal" in cap_html.lower() or "/이벤트설정" in cap_html: media_group_cache[m_id]["caption"] = cap_html
            if media_group_cache[m_id]["task"]: media_group_cache[m_id]["task"].cancel()
            media_group_cache[m_id]["task"] = asyncio.create_task(save_logic(m_id, chat_id, context))
            return

    # 당첨 이벤트
    if not is_private and not update.message.from_user.is_bot:
        if message_counter > 0 and message_counter % 5000 == 0:
            if "_event_celebration_" in db_commands: await send_custom_output(context, chat_id, db_commands["_event_celebration_"], f"🎊 {message_counter}번째 당첨! 🎊")

    # 커스텀 명령어
    if text.startswith(('/', '!')):
        cmd = re.sub(r"^[ /!]+", "", text.split()[0]).strip()
        if cmd in db_commands: await send_custom_output(context, chat_id, db_commands[cmd])

async def save_logic(m_id, chat_id, context):
    global db_commands, message_counter
    await asyncio.sleep(2.5)
    if m_id in media_group_cache:
        target, raw_cap = media_group_cache[m_id], media_group_cache[m_id]["caption"]
        try:
            if "/이벤트설정" in raw_cap: key, content = "_event_celebration_", raw_cap.split("/이벤트설정", 1)[1].strip()
            else:
                match = re.search(r"/personal\s+(\S+)\s*(.*)", raw_cap, re.IGNORECASE | re.DOTALL)
                if match: key, content = match.group(1), match.group(2)
                else: return
            msg, btn = content, ""
            if "---" in content: msg, btn = content.rsplit("---", 1)
            db_commands[key] = {"photos": target["ids"], "caption": msg.strip(), "buttons": re.sub('<[^<]+?>', '', btn).strip()}
            save_bot_data(db_commands, message_counter)
            await context.bot.send_message(chat_id, f"✅ [{key}] 영구 저장")
        except: pass
        del media_group_cache[m_id]

async def send_custom_output(context, chat_id, data, title=""):
    try:
        photos, caption = data["photos"], f"<b>{title}</b>\n\n{data['caption']}" if title else data['caption']
        markup = None
        if data.get("buttons"):
            keyboard = []
            for line in data["buttons"].strip().split('\n'):
                row = [InlineKeyboardButton(btn.split('|')[0].strip(), url=btn.split('|')[1].strip()) for btn in line.split('&&') if '|' in btn]
                if row: keyboard.append(row)
            markup = InlineKeyboardMarkup(keyboard) if keyboard else None
        if len(photos) == 1: await context.bot.send_photo(chat_id, photos[0], caption=caption, parse_mode="HTML", reply_markup=markup)
        else:
            media = [InputMediaPhoto(photos[0], caption=caption, parse_mode="HTML")] + [InputMediaPhoto(fid) for fid in photos[1:]]
            await context.bot.send_media_group(chat_id, media)
            if markup: await context.bot.send_message(chat_id, "⚡️ 버튼 확인", reply_markup=markup)
    except: pass

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global db_commands, message_counter
    query = update.callback_query
    if query.from_user.id == ADMIN_ID and query.data.startswith("del_"):
        cmd = query.data.replace("del_", "")
        if cmd in db_commands:
            del db_commands[cmd]
            save_bot_data(db_commands, message_counter)
            await query.edit_message_text(f"🗑️ [{cmd}] 삭제 완료")

if __name__ == "__main__":
    if TOKEN and MONGO_URL:
        threading.Thread(target=run_flask, daemon=True).start()
        app = ApplicationBuilder().token(TOKEN).build()
        app.add_handler(MessageHandler(filters.ALL, handle_message))
        app.add_handler(CallbackQueryHandler(handle_callback))
        app.run_polling()
