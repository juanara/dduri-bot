import os, re, threading, asyncio, logging, random, html, json, requests
from telegram import Update, InputMediaPhoto, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes, CallbackQueryHandler
from flask import Flask

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

# 3. 데이터 저장 및 로드
DB_FILE = "database.json"

def load_db():
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except: pass
    return {"commands": {}, "counter": 0}

def save_db(data):
    try:
        with open(DB_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
    except Exception as e:
        logging.error(f"DB 저장 오류: {e}")

current_data = load_db()
db = current_data.get("commands", {})
message_counter = current_data.get("counter", 0)
media_group_cache = {}

# 4. 실시간 날씨 함수
async def get_realtime_weather(city_input="수원"):
    if not WEATHER_API_KEY:
        return "❌ Render 환경변수에 WEATHER_API_KEY를 등록해주세요."
    city_map = {"수원": "Suwon", "서울": "Seoul", "인천": "Incheon", "부산": "Busan", "제주": "Jeju"}
    city_name = city_map.get(city_input, city_input)
    try:
        url = f"http://api.openweathermap.org/data/2.5/weather?q={city_name}&appid={WEATHER_API_KEY}&units=metric&lang=kr"
        response = requests.get(url, timeout=5)
        data = response.json()
        if data.get("cod") == 200:
            weather_desc, temp, feels_like, icon = data["weather"][0]["description"], data["main"]["temp"], data["main"]["feels_like"], data["weather"][0]["icon"]
            emoji = "☀️" if "01" in icon else "☁️" if "02" in icon or "03" in icon or "04" in icon else "🌧️" if "09" in icon or "10" in icon else "⚡" if "11" in icon else "❄️" if "13" in icon else "🌫️"
            return (f"📍 <b>{city_input} 실시간 날씨</b> {emoji}\n\n🌡️ <b>현재 기온:</b> {temp}°C\n🤔 <b>체감 온도:</b> {feels_like}°C\n📝 <b>날씨 상태:</b> {weather_desc}\n\n✨ 실시간 정보입니다")
        return "❌ 지역을 찾을 수 없습니다."
    except: return "⚠️ 날씨 서버 연결 오류"

# 5. 메뉴 추천 로직
def get_menu_recommendation(command):
    morning = ["전복죽", "계란 토스트", "시리얼", "에그 베네딕트", "과일 샐러드", "단호박 스프", "그릭 요거트", "편의점 주먹밥", "누룽지탕", "베이글과 크림치즈", "스크램블 에그", "바나나 한 개", "모닝 샌드위치", "순두부 한 그릇", "미역국 백반", "프렌치 토스트", "야채 호빵", "콩나물국밥", "닭가슴살 쉐이크", "팬케이크", "새우 완탕", "딤섬", "구운 계란과 우유", "연어 오픈 샌드위치", "시금치 프리타타", "김가루 주먹밥", "블루베리 머핀", "따뜻한 두유", "아침 보리밥", "브런치 플래터"]
    dinner = ["삼겹살에 소주", "치킨과 맥주", "페퍼로니 피자", "모듬 회와 매운탕", "소곱창 구이", "불족발", "해물 파스타", "립아이 스테이크", "소고기 샤브샤브", "매콤 닭볶음탕", "간장 갈비찜", "김치찜과 두부", "골뱅이 소면", "모듬 초밥", "감자탕", "감바스와 바게트", "곱창전골", "한우 등심구이", "찜닭", "양꼬치와 칭따오", "보쌈 정식", "물회", "쭈꾸미 볶음", "LA 갈비", "해물찜", "스키야키", "훈제 오리 구이", "낙곱새", "등갈비찜", "매운 당면 떡볶이"]
    coffee = ["카페 아메리카노", "카페 라떼", "돌체 라떼", "카라멜 마끼아또", "자바 칩 프라푸치노", "쿨 라임 피지오", "자몽 허니 블랙 티", "핑크 드링크 에이드", "에스프레소 프라푸치노", "제주 말차 라떼", "바닐라 플랫 화이트", "콜드 브루", "돌체 콜드 브루", "민트 초콜릿 칩 블렌디드", "딸기 딜라이트 요거트", "화이트 초콜릿 모카", "카푸치노", "시그니처 핫 초콜릿", "더블 에스프레소 칩 프라푸치노", "얼 그레이 티 라떼", "차이 티 라떼", "망고 바나나 블렌디드", "유스베리 티", "브렉퍼스트 블렌드 블랙 티", "허니 자몽 블랙 티 에이드", "블랙 글레이즈드 라떼", "바닐라 크림 콜드 브루", "슈크림 라떼", "피치 딸기 피지오", "망고 패션 티 블렌디드"]
    snack = ["시장 떡볶이", "핫도그", "바삭한 크로플", "츄러스", "뚱카롱", "호도과자", "에그타르트", "육포와 땅콩", "버터구이 오징어", "초코칩 쿠키", "소프트 아이스크림", "계절 과일", "군고구마", "군밤", "포테이토 칩", "찐옥수수", "닭강정", "회오리 감자", "소떡소떡", "붕어빵", "호떡", "꽈배기", "나초와 치즈딥", "팝콘", "치즈볼", "구운 쥐포", "요거트 아이스크림", "단팥빵", "생크림 케이크", "에너지바"]

    if "/아메추" in command: res, cat = random.choice(morning), "아침 ☀️"
    elif "/저메추" in command: res, cat = random.choice(dinner), "저녁 🌙"
    elif "/커추" in command: res, cat = random.choice(coffee), "스타벅스 ☕"
    elif "/간추" in command: res, cat = random.choice(snack), "간식 🥨"
    else: res, cat = random.choice(["제육볶음", "김치찌개", "돈까스", "짜장면", "쌀국수", "샌드위치", "텐동", "덮밥", "라멘", "초밥"]), "점심 🍴"
    
    comments = ["오늘 이거 먹으면 기분 최고! 🔥", "탁월한 선택이네요! 😋", "결정하기 힘들 땐 역시 이게 최고죠! ✨", "든든하게 드시고 기운 내세요! 💪"]
    return f"🍴 <b>{cat} 추천</b>\n\n추천 메뉴: <b>{res}</b>\n\n💬 <i>{random.choice(comments)}</i>"

# 6. 주사위 확률
def get_weighted_dice():
    seed = random.random() * 100
    if seed < 0.1: return random.randrange(40000, 50001, 500)
    elif seed < 1.1: return random.randrange(30000, 40000, 500)
    elif seed < 4.1: return random.randrange(10000, 30000, 500)
    elif seed < 8.1: return random.randrange(5000, 10000, 500)
    else: return random.randrange(500, 5000, 500)

# 7. 버튼 및 전송 로직
def build_button_markup(button_data):
    if not button_data: return None
    keyboard = []
    for line in button_data.strip().split('\n'):
        row = [InlineKeyboardButton(btn.split('|')[0].strip(), url=btn.split('|')[1].strip()) for btn in line.split('&&') if '|' in btn]
        if row: keyboard.append(row)
    return InlineKeyboardMarkup(keyboard) if keyboard else None

async def send_custom_output(context, chat_id, data, title=""):
    try:
        photos, caption = data["photos"], f"<b>{title}</b>\n\n{data['caption']}" if title else data['caption']
        markup = build_button_markup(data.get("buttons", ""))
        if len(caption) <= 1000:
            if len(photos) == 1: await context.bot.send_photo(chat_id, photos[0], caption=caption, parse_mode="HTML", reply_markup=markup)
            else:
                media = [InputMediaPhoto(photos[0], caption=caption, parse_mode="HTML")] + [InputMediaPhoto(fid) for fid in photos[1:]]
                await context.bot.send_media_group(chat_id, media)
                if markup: await context.bot.send_message(chat_id, "⚡️ 아래 버튼 확인", reply_markup=markup, parse_mode="HTML")
        else:
            if len(photos) == 1: await context.bot.send_photo(chat_id, photos[0])
            else: await context.bot.send_media_group(chat_id, [InputMediaPhoto(fid) for fid in photos])
            await context.bot.send_message(chat_id, caption, reply_markup=markup, parse_mode="HTML")
    except Exception as e: logging.error(f"전송 에러: {e}")

async def delete_messages_later(context: ContextTypes.DEFAULT_TYPE, chat_id: int, message_ids: list, delay: float):
    await asyncio.sleep(delay)
    for msg_id in message_ids:
        if msg_id:
            try: await context.bot.delete_message(chat_id=chat_id, message_id=msg_id)
            except: pass 

# 8. 메인 메시지 핸들러
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global db, message_counter, media_group_cache
    if not update.message: return
    uid, text = update.message.from_user.id, update.message.text or ""
    cap_html, is_private, chat_id = update.message.caption_html or "", update.effective_chat.type == "private", update.effective_chat.id

    if not update.message.from_user.is_bot:
        # 하우돈 검거 (2.5초 삭제)
        banned_words = ["니노", "노무현", "무현", "노무"]
        if any(word in text for word in banned_words) or any(word in cap_html for word in banned_words):
            reply = f"<tg-spoiler>{random.choice(['베충아!! 우도나!! ㅋㅋㅋ', '또 우도니너지?! 🤨', '하우돈 검거 완료 👮‍♂️'])}</tg-spoiler>"
            bot_reply = await update.message.reply_text(reply, parse_mode="HTML")
            sticker_msg = None
            if os.path.exists("2.webm"):
                try:
                    with open("2.webm", "rb") as f: sticker_msg = await context.bot.send_sticker(chat_id=chat_id, sticker=f)
                except: pass
            msgs = [update.message.message_id, bot_reply.message_id]
            if sticker_msg: msgs.append(sticker_msg.message_id)
            asyncio.create_task(delete_messages_later(context, chat_id, msgs, 2.5))
            return 

        # 분부니/뷰니 찬양 (3초 삭제)
        s_count = text.count('ㅅ')
        if ("분부니" in text and s_count >= 6) or ("뷰니" in text and s_count >= 5):
            reply = random.choice(["대여왕 강림!!! ㅅㅅㅅㅅ 👑", "여왕님 충성충성 ^^7 👸", "폼 미쳤다이! 🥳"])
            bot_reply = await update.message.reply_text(reply, parse_mode="HTML")
            sticker_msg, audio_msg = None, None
            if os.path.exists("1.webm"):
                try:
                    with open("1.webm", "rb") as f: sticker_msg = await context.bot.send_sticker(chat_id=chat_id, sticker=f)
                except: pass
            if os.path.exists("1.ogg"):
                try:
                    with open("1.ogg", "rb") as f: audio_msg = await context.bot.send_voice(chat_id=chat_id, voice=f)
                except: pass
            msgs = [update.message.message_id, bot_reply.message_id]
            if sticker_msg: msgs.append(sticker_msg.message_id)
            if audio_msg: msgs.append(audio_msg.message_id)
            asyncio.create_task(delete_messages_later(context, chat_id, msgs, 3.0))
            return

        # ㅅ 9개 이상/무욱자
        elif "무욱자" in text and s_count >= 4:
            return await update.message.reply_text("우욱자갓 ㅅㅅㅅㅅ 미친 폼!! 🔥", parse_mode="HTML")
        elif s_count >= 9 or text.count('ㅆ') >= 9:
            return await update.message.reply_text("개나이스! 앙 기모링~~ 폼 미쳤다이! 🔥", parse_mode="HTML")

    # [메뉴 추천 기능 - 5초 뒤 명령어와 답변 동시 삭제 ⭐]
    menu_cmds = ["/아메추", "/점메추", "/저메추", "/커추", "/간추"]
    if any(text.startswith(c) for c in menu_cmds):
        res_text = get_menu_recommendation(text)
        bot_reply = await update.message.reply_text(res_text, parse_mode="HTML")
        asyncio.create_task(delete_messages_later(context, chat_id, [update.message.message_id, bot_reply.message_id], 5.0))
        return

    # [날씨 - 5초 뒤 자동 삭제]
    if text.startswith("/날씨"):
        parts = text.split()
        city = parts[1] if len(parts) > 1 else "수원"
        res = await get_realtime_weather(city)
        bot_reply = await update.message.reply_text(res, parse_mode="HTML")
        asyncio.create_task(delete_messages_later(context, chat_id, [update.message.message_id, bot_reply.message_id], 5.0))
        return

    # 주사위 / 관리자 / 카운팅 등 기존 로직 유지
    if text in ["/주사위", "!주사위"]:
        res, name = get_weighted_dice(), html.escape(update.message.from_user.first_name)
        icon = "💎" if res >= 40000 else "🔥" if res >= 10000 else "🎲"
        return await update.message.reply_text(f"<b>{name}</b>님의 결과: {icon} <b>{res:,}</b>", parse_mode="HTML")

    if uid == ADMIN_ID and is_private:
        if text == "/카운트확인": return await update.message.reply_text(f"📊 카운트: <b>{message_counter}</b>", parse_mode="HTML")
        if text == "/카운트리로드":
            message_counter = 0
            save_db({"commands": db, "counter": message_counter})
            return await update.message.reply_text("🔢 초기화 완료")
        if text in ["/리스트", "/삭제"]:
            btns = [[InlineKeyboardButton(f"🗑️ {k} 삭제", callback_data=f"del_{k}")] for k in db.keys()]
            return await update.message.reply_text("📋 삭제 리스트:", reply_markup=InlineKeyboardMarkup(btns))
        if update.message.photo:
            m_id = update.message.media_group_id or f"s_{update.message.message_id}"
            if m_id not in media_group_cache: media_group_cache[m_id] = {"ids": [], "caption": "", "task": None}
            media_group_cache[m_id]["ids"].append(update.message.photo[-1].file_id)
            if "/personal" in cap_html.lower() or "/이벤트설정" in cap_html: media_group_cache[m_id]["caption"] = cap_html
            if media_group_cache[m_id]["task"]: media_group_cache[m_id]["task"].cancel()
            media_group_cache[m_id]["task"] = asyncio.create_task(save_logic(m_id, update.message.chat_id, context))
            return

    if not is_private and not text.startswith(('/', '!')) and not cap_html.startswith('/'):
        message_counter += 1
        if message_counter % 100 == 0: save_db({"commands": db, "counter": message_counter})
        if message_counter > 0 and message_counter % 5000 == 0:
            if "_event_celebration_" in db: await send_custom_output(context, update.message.chat_id, db["_event_celebration_"], f"🎊 {message_counter}번째 당첨! 🎊")

    if text.startswith(('/', '!')):
        cmd = re.sub(r"^[ /!]+", "", text.split()[0]).strip()
        if cmd in db: await send_custom_output(context, update.message.chat_id, db[cmd])

async def save_logic(m_id, chat_id, context):
    global db, message_counter
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
            db[key] = {"photos": target["ids"], "caption": msg.strip(), "buttons": re.sub('<[^<]+?>', '', btn).strip()}
            save_db({"commands": db, "counter": message_counter})
            await context.bot.send_message(chat_id, f"✅ [{key}] 등록 완료")
        except: pass
        del media_group_cache[m_id]

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global db, message_counter
    query = update.callback_query
    if query.from_user.id == ADMIN_ID and query.data.startswith("del_"):
        cmd = query.data.replace("del_", "")
        if cmd in db:
            del db[cmd]
            save_db({"commands": db, "counter": message_counter})
            await query.edit_message_text(f"🗑️ [{cmd}] 삭제 완료")

if __name__ == "__main__":
    if TOKEN:
        threading.Thread(target=run_flask, daemon=True).start()
        app = ApplicationBuilder().token(TOKEN).build()
        app.add_handler(MessageHandler(filters.ALL, handle_message))
        app.add_handler(CallbackQueryHandler(handle_callback))
        app.run_polling()
