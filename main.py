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
        return "❌ Render 환경변수에 WEATHER_API_KEY를 등록해주세요"
    city_map = {
        "수원": "Suwon", "서울": "Seoul", "인천": "Incheon", 
        "부산": "Busan", "대구": "Daegu", "대전": "Daejeon", 
        "광주": "Gwangju", "울산": "Ulsan", "제주": "Jeju"
    }
    city_name = city_map.get(city_input, city_input)
    try:
        url = f"http://api.openweathermap.org/data/2.5/weather?q={city_name}&appid={WEATHER_API_KEY}&units=metric&lang=kr"
        response = requests.get(url, timeout=5)
        data = response.json()
        if data.get("cod") == 200:
            weather_desc = data["weather"][0]["description"]
            temp = data["main"]["temp"]
            feels_like = data["main"]["feels_like"]
            icon = data["weather"][0]["icon"]
            emoji = "☀️" if "01" in icon else "☁️" if "02" in icon or "03" in icon or "04" in icon else "🌧️" if "09" in icon or "10" in icon else "⚡" if "11" in icon else "❄️" if "13" in icon else "🌫️"
            return (f"📍 <b>{city_input} 실시간 날씨</b> {emoji}\n\n"
                    f"🌡️ <b>현재 기온:</b> {temp}°C\n"
                    f"🤔 <b>체감 온도:</b> {feels_like}°C\n"
                    f"📝 <b>날씨 상태:</b> {weather_desc}\n\n"
                    f"✨ 실시간 정보입니다")
        return "❌ 지역을 찾을 수 없습니다"
    except: return "⚠️ 날씨 서버 연결 오류"

# 5. 점심 메뉴 추천
def get_lunch_recommendation():
    menu_list = [
        ("한식 🍚", ["김치찌개와 계란말이", "제육볶음과 쌈밥", "뜨끈한 순대국밥", "뼈해장국", "비빔밥과 된장찌개", "부대찌개", "갈비탕", "육회비빔밥", "닭갈비", "보쌈정식"]),
        ("중식 🍜", ["짜장면과 군만두", "해물짬뽕", "마라탕과 꿔바로우", "볶음밥", "잡채밥", "마파두부 덮밥", "탕수육 정식", "차돌짬뽕"]),
        ("일식 🍣", ["바삭한 로스카츠", "치즈카츠", "모듬초밥", "사케동(연어덮밥)", "가츠동", "규동(소고기덮밥)", "돈코츠 라멘", "미소 라멘", "텐동"]),
        ("양식 🍕", ["수제 치즈버거", "베이컨 크림 파스타", "매콤한 토마토 파스타", "페퍼로니 피자", "안심 스테이크", "치킨 리조또"]),
        ("아시안/기타 🍲", ["소고기 쌀국수", "팟타이", "나시고랭", "인도식 커리와 난", "분짜", "멕시칸 타코"]),
        ("분식/가벼운 식사 🥪", ["떡볶이와 모듬튀김", "돈까스 김밥 반줄 세트", "잔치국수", "연어 샐러드", "이삭토스트", "서브웨이 꿀조합"])
    ]
    category, items = random.choice(menu_list)
    menu = random.choice(items)
    comments = ["오늘 이거 먹으면 기분 최고! 🔥", "탁월한 선택이네요! 맛있게 드세요. 😋", "결정하기 힘들 땐 역시 이게 최고죠! ✨", "든든하게 드시고 기운 내세요! 💪"]
    return (f"🍴 <b>오늘의 점심 추천</b>\n\n종류: <b>{category}</b>\n메뉴: <b>{menu}</b>\n\n💬 <i>{random.choice(comments)}</i>")

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

# ⭐ 다중 메시지 자동 삭제 기능 ⭐
async def delete_messages_later(context: ContextTypes.DEFAULT_TYPE, chat_id: int, message_ids: list, delay: float):
    await asyncio.sleep(delay)
    for msg_id in message_ids:
        if msg_id:
            try:
                await context.bot.delete_message(chat_id=chat_id, message_id=msg_id)
            except: pass 

# 8. 메인 메시지 핸들러
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global db, message_counter, media_group_cache
    if not update.message: return
    
    uid = update.message.from_user.id
    text = update.message.text or ""
    cap_html = update.message.caption_html or ""
    is_private = update.effective_chat.type == "private"
    chat_id = update.effective_chat.id

    if not update.message.from_user.is_bot:
        # ⭐ [하우돈 검거 로직 (2.5초 삭제)] ⭐
        banned_words = ["니노", "노무현", "무현", "노무"]
        if any(word in text for word in banned_words) or any(word in cap_html for word in banned_words):
            hawoodon_responses = ["베충아!! 우도나!! ㅋㅋㅋ", "또 우도니너지?! 🤨", "아이고 우돈아 또 시작이냐 ㅋㅋㅋ", "하우돈 검거 완료 👮‍♂️", "우도니 폼 미쳤네 ㅋㅋㅋ", "하우돈 또 너야? ㅋㅋㅋㅋ", "우도니 뇌절 멈춰! 🛑"]
            reply_text = f"<tg-spoiler>{random.choice(hawoodon_responses)}</tg-spoiler>"
            bot_reply = await update.message.reply_text(reply_text, parse_mode="HTML")
            sticker_msg = None
            udon_stickers = ["2.webm", "2.webp", "3.webp"]
            chosen = random.choice(udon_stickers)
            if os.path.exists(chosen):
                try:
                    with open(chosen, "rb") as f: sticker_msg = await context.bot.send_sticker(chat_id=chat_id, sticker=f)
                except: pass
            msgs = [update.message.message_id, bot_reply.message_id]
            if sticker_msg: msgs.append(sticker_msg.message_id)
            asyncio.create_task(delete_messages_later(context, chat_id, msgs, 2.5))
            return 

        # ⭐ [분부니/뷰니 찬양 (3초 삭제)] ⭐
        s_count = text.count('ㅅ')
        if ("분부니" in text and s_count >= 6) or ("뷰니" in text and s_count >= 5):
            if "분부니" in text:
                congrats = ["대여왕 분부니 강림!!! ㅅㅅㅅㅅ 폼 미쳤다이! 👑", "킹왕짱 분부니 여왕님 충성충성 ^^7 ㅅㅅㅅㅅ 👸", "분부니 폼 도라방스;; 🍀", "분부니 여왕님 나이스샷~!! 축하드립니당 🥳"]
            else:
                congrats = ["뷰코뷰코니!! 우리 여왕님 폼 찢었다 ㅅㅅㅅㅅ 👑", "갓뷰니 등장!! 완전 럭키비키잔앙~~ 🍀", "대여왕 뷰니 찬양하라!! 폼 도라방스;; 🔥", "뷰코뷰코니 폼 미쳤다이!! 🥳"]
            
            bot_reply = await update.message.reply_text(random.choice(congrats), parse_mode="HTML")
            sticker_msg = None
            if os.path.exists("1.webm"):
                try:
                    with open("1.webm", "rb") as f: sticker_msg = await context.bot.send_sticker(chat_id=chat_id, sticker=f)
                except: pass
            audio_msg = None
            if os.path.exists("1.ogg"):
                try:
                    with open("1.ogg", "rb") as f: audio_msg = await context.bot.send_voice(chat_id=chat_id, voice=f)
                except: pass
            msgs = [update.message.message_id, bot_reply.message_id]
            if sticker_msg: msgs.append(sticker_msg.message_id)
            if audio_msg: msgs.append(audio_msg.message_id)
            asyncio.create_task(delete_messages_later(context, chat_id, msgs, 3.0))
            return

        elif "무욱자" in text and s_count >= 4:
            muukja_congrats = ["우욱자갓 ㅅㅅㅅㅅㅅㅅㅅ 미친 폼 도라방스!! 🔥", "무욱자 폼 미쳤다이!! 🍀", "갓욱자 등장!! 앙 기모링~~ 🚀"]
            await update.message.reply_text(random.choice(muukja_congrats), parse_mode="HTML")
            return 

        elif s_count >= 9 or text.count('ㅆ') >= 9:
            mz_congrats = ["개나이스! 앙 기모링~~ 폼 미쳤다이! 🔥", "추카드립니더 ㅅㅅㅅ 오늘 저녁은 소고기 가즈아~ 🥩", "와 찢었다;; 레전드 갱신 ㅊㅋㅊㅋ 🚀", "대박사건 ㄷㄷ 완전 럭키비키잔앙~ 🍀", "나이스샷~~! 폼 진짜 도라방스네요 ㅊㅋㅊㅋ 🎉🎉"]
            await update.message.reply_text(random.choice(mz_congrats), parse_mode="HTML")
            return

    # [점메추]
    if text.startswith("/점메추"):
        return await update.message.reply_text(get_lunch_recommendation(), parse_mode="HTML")

    # ⭐ [실시간 날씨 - 5초 뒤 명령어와 답변 동시 삭제] ⭐
    if text.startswith("/날씨"):
        parts = text.split()
        city = parts[1] if len(parts) > 1 else "수원"
        res = await get_realtime_weather(city)
        bot_reply = await update.message.reply_text(res, parse_mode="HTML")
        
        # 유저가 친 명령어(update.message.message_id)와 봇의 답변(bot_reply.message_id)을 5초 뒤 삭제
        msgs_to_del = [update.message.message_id, bot_reply.message_id]
        asyncio.create_task(delete_messages_later(context, chat_id, msgs_to_del, 5.0))
        return

    # [주사위 / 관리자 기능 / 카운팅 / 명령어 실행 - 기존과 동일]
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
            if not db: return await update.message.reply_text("❌ 데이터 없음")
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
