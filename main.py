import os, re, threading, asyncio, logging, html, requests, time
import urllib.parse
import random
from datetime import datetime, timedelta, timezone
from telegram import Update, InputMediaPhoto, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes, CallbackQueryHandler
from flask import Flask, request, jsonify
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

# 관리자 설정 대응
ADMIN_ID_STR = os.getenv("ADMIN_ID", "8092185425")
ADMIN_LIST = [int(i.strip()) for i in ADMIN_ID_STR.split(",") if i.strip()]

client = MongoClient(MONGO_URL)
mongodb = client['dduri_bot_db']
col_main, col_members, col_sched, col_sessions = mongodb['settings'], mongodb['members'], mongodb['schedules'], mongodb['admin_sessions']
col_scores = mongodb['game_scores']

# 한일 야구장 정밀 좌표 매핑 데이터 (KBO 10개, NPB 12개)
STADIUMS = {
    "KBO (한국)": {
        "잠실 (LG/두산)": {"lat": 37.5122, "lon": 127.0719},
        "고척 (키움)": {"lat": 37.4982, "lon": 126.8671},
        "문학 (SSG)": {"lat": 37.4371, "lon": 126.6933},
        "수원 (KT)": {"lat": 37.2997, "lon": 127.0101},
        "대전 (한화)": {"lat": 36.3172, "lon": 127.4292},
        "대구 (삼성)": {"lat": 35.8412, "lon": 128.6815},
        "광주 (KIA)": {"lat": 35.1683, "lon": 126.8891},
        "사직 (롯데)": {"lat": 35.1940, "lon": 129.0614},
        "창원 (NC)": {"lat": 35.2224, "lon": 128.5812},
        "울산 (문수)": {"lat": 35.5312, "lon": 129.2594}
    },
    "NPB (일본)": {
        "도쿄돔 (요미우리)": {"lat": 35.7056, "lon": 139.7519},
        "진구 (야쿠르트)": {"lat": 35.6744, "lon": 139.7170},
        "요코하마 (디엔에이)": {"lat": 35.4434, "lon": 139.6400},
        "고시엔 (한신)": {"lat": 34.7212, "lon": 135.3616},
        "교세라돔 (오릭스)": {"lat": 34.6694, "lon": 135.4761},
        "반테린돔 (주니치)": {"lat": 35.1859, "lon": 136.9475},
        "마쓰다 (히로시마)": {"lat": 34.3918, "lon": 132.4847},
        "에스콘필드 (니혼햄)": {"lat": 42.9902, "lon": 141.5540},
        "라쿠텐모바일 (라쿠텐)": {"lat": 38.2565, "lon": 140.9025},
        "벨루나돔 (세이부)": {"lat": 35.7686, "lon": 139.4205},
        "조조마린 (치바롯데)": {"lat": 35.6452, "lon": 140.0312},
        "페이페이돔 (소프트뱅크)": {"lat": 33.5954, "lon": 130.3622}
    }
}

# 텔레톤 유저봇 및 캐시 초기화
userbot = TelegramClient(StringSession(STRING_SESSION), API_ID, API_HASH)
media_group_cache = {}

# 전역 상태 관리
box_event_rooms = {}

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

# 지연 삭제 비동기 태스크 모듈
async def delete_messages_delayed(context: ContextTypes.DEFAULT_TYPE, chat_id: int, message_ids: list, delay: float = 3.0):
    await asyncio.sleep(delay)
    for msg_id in message_ids:
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=msg_id)
        except Exception as e:
            logging.error(f"메시지 자동 삭제 실패 (ID: {msg_id}): {e}")

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

# 엔진 3 스케줄러 루프 (30~55분 랜덤 가변 낙하 모듈 탑재 완료판)
async def custom_scheduler_loop(application):
    global box_event_rooms
    await asyncio.sleep(10)
    bot = application.bot
    
    # 첫 구동 시점의 다음 상자 투하 타임스탬프를 [현재 시간 + 30~55분 랜덤 값]으로 정밀 동기화
    next_box_ts = datetime.now(KST).timestamp() + random.randint(30, 55) * 60
    
    while True:
        try:
            now = datetime.now(KST)
            now_ts = now.timestamp()
            now_date, now_time = now.strftime("%Y%m%d"), now.strftime("%H%M")
            
            # 무작위로 추려진 다음 연합상자 투하 타임라인 도달 시 실행
            if now_ts >= next_box_ts:
                # 실행과 동시에 다음 낙하 사이클을 다시 30~55분 사이의 무작위 난수로 롤링 갱신
                next_box_ts = now_ts + random.randint(30, 55) * 60
                
                for r in list(col_members.find()):
                    r_chat_id = str(r['chat_id'])
                    
                    # 상자 획득 제어 세션을 강제 True 개방
                    box_event_rooms[r_chat_id] = True
                    try:
                        await bot.send_message(
                            chat_id=int(r_chat_id),
                            text="📦 <b>연합상자가 출현했습니다!</b>\n /가족방최고 혹은 !가족방최고 를 먼저 쳐주신 1분에게 랜덤 포인트를 지급합니다!",
                            parse_mode="HTML"
                        )
                    except: pass

            # 기존 일반 예약 스케줄 서칭 로직
            for s in list(col_sched.find()):
                if not (s['start_dt'] <= now_date <= s['end_dt']):
                    if now_date > s['end_dt']: col_sched.delete_one({"_id": s['_id']})
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
        
        # 가변 정밀 스캔 타이밍 보정을 위해 체크 주기를 10초로 동기화합니다.
        await asyncio.sleep(10)

# 엔진 4 저장 로직
async def save_logic_with_delay(chat_id, context, m_id, message=None):
    if m_id: await asyncio.sleep(3.5)
    raw_html = media_group_cache[m_id]["caption"] if m_id else (message.caption_html or message.text_html or "")
    sess = col_sessions.find_one({"admin_id": {"$in": ADMIN_LIST}})
    t_id = sess['target_chat_id'] if sess else None
    if not t_id: return await context.bot.send_message(chat_id, "⚠️ 설정 명령어로 방을 먼저 선택하세요")
    
    try:
        cleaned = raw_html.strip()
        cleaned = re.sub(r'</?(pre|code)[^>]*>', '', cleaned)
        cleaned_lower = cleaned.lower()
        
        if "/스케줄등록" in cleaned_lower:
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
            
        elif "/personal" in cleaned_lower:
            m = re.search(r"/personal\s+(\S+)\s*(.*)", cleaned, re.IGNORECASE | re.DOTALL)
            if not m: raise ValueError("퍼스널 등록 형식이 올바르지 않습니다")
            
            key = clean_tags(m.group(1))
            content = m.group(2)
            
            msg, btn = content.rsplit("---", 1) if "---" in content else (content, "")
            cmd_data = {"photos": (media_group_cache[m_id]["ids"] if m_id else []), "caption": balance_html(msg.strip()), "buttons": re.sub('<[^<]+?>', '', btn).strip()}
            
            if t_id == "common": 
                col_main.update_one({"id": "bot_main_data"}, {"$set": {f"commands.{key}": cmd_data}}, upsert=True)
            else: 
                col_members.update_one({"chat_id": t_id}, {"$set": {f"local_commands.{key}": cmd_data}}, upsert=True)
            await context.bot.send_message(chat_id, f"✅ {key} 저장 완료")
            
    except Exception as e: 
        await context.bot.send_message(chat_id, f"❌ 에러 발생 {clean_tags(str(e))}")
    if m_id in media_group_cache: del media_group_cache[m_id]

# 메인 핸들러
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global box_event_rooms
    if not update.message: return
    uid, text, chat_id = update.effective_user.id, (update.message.text or "").strip(), update.effective_chat.id
    uname = update.effective_user.first_name
    
    # [최상단 배치 고정] 관리자 전용 미참여자 포함 방 전체 실시간 명단 격리 조회 엔진
    if text.startswith('/유저조회'):
        if uid not in ADMIN_LIST or update.effective_chat.type != "private": return
        sess = col_sessions.find_one({"admin_id": uid})
        t_id = sess['target_chat_id'] if sess else None
        if not t_id: return await update.message.reply_text("⚠️ /설정 명령어로 먼저 관리할 방을 선택하세요.")
        room = col_members.find_one({"chat_id": t_id})
        if not room: return await update.message.reply_text("❌ 방 정보가 없습니다. 해당 방에서 /동기화를 먼저 해주세요.")
        
        users = room.get("users", {})
        joined_users = {str(r['user_id']): r['user_name'] for r in col_scores.find({"chat_id": str(t_id)})}
        
        msg = f"👥 <b>방({room.get('room_name')}) 유저 참여 현황</b>\n\n"
        for u_id, name in users.items():
            status = "✅ 참여" if u_id in joined_users else "❌ 미참여"
            msg += f"{name} (<code>{u_id}</code>) : {status}\n"
        await update.message.reply_text(msg, parse_mode="HTML")
        return

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

    if text.startswith(('/game', '!game', '/게임', '!게임')):
        u_encoded = urllib.parse.quote(uname)
        url_snake = f"https://dduri-bot.onrender.com/game/snake?chat_id={chat_id}&user_id={uid}&user_name={u_encoded}"
        keyboard = [[InlineKeyboardButton(text="🐍 레트로 지렁이게임 시작", url=url_snake)]]
        await update.message.reply_text("🕹 <b>뜌리 인앱 게임센터</b>\n\n아래 버튼을 누르면 모바일 가상 패드가 장착된 지렁이게임이 즉시 시작됩니다.", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
        return

    if text.startswith(('/score', '!score', '/스코어', '!스코어')):
        url_live = f"https://dduri-bot.onrender.com/sports/live"
        keyboard = [[InlineKeyboardButton(text="📊 실시간 스포츠 스코어센터 진입", url=url_live)]]
        await update.message.reply_text("📣 <b>뜌리 라이브 스코어센터</b>\n\n아래 버튼을 누르면 기기별 크기에 최적화된 실시간 경기 상황판이 열립니다.", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
        return

    if text.startswith(('/랭킹', '!랭킹', '/ranking', '!ranking')):
        point_records = list(col_scores.find({"chat_id": str(chat_id), "game": "snake"}).sort("score", -1).limit(10))
        msg = "🏆 <b>우리 방 실시간 보유 포인트 TOP 10 순위표</b>\n\n"
        if not point_records: msg += "→ 아직 등록된 포인트 기록이 없습니다.\n"
        for idx, r in enumerate(point_records, 1):
            msg += f" {idx}위 : {r['user_name']} <code>{r['user_id']}</code> - {r['score']}포인트\n"
        await update.message.reply_text(msg, parse_mode="HTML")
        return

    if text.startswith(('/점메추', '!점메추', '/저메추', '!저메추', '/커추', '!커추')):
        lunch_menu = ["김치찌개", "된장찌개", "부대찌개", "제육볶음", "돈까스", "짜장면", "짬뽕", "볶음밥", "탕수욕", "김밥", "라면", "떡볶이", "순대", "순대국밥", "뼈해장국", "설렁탕", "갈비탕", "육개장", "비빔밥", "칼국수", "수제비", "물냉면", "비빔냉면", "우동", "초밥", "회덮밥", "파스타", "피자", "햄버거", "샌드위치"]
        dinner_menu = ["삼겹살", "돼지갈비", "소고기구이", "닭갈비", "치킨", "족발", "보쌈", "곱창구이", "막창구이", "곱창전골", "아구찜", "해물찜", "찜닭", "닭볶음탕", "감자탕", "샤브샤브", "스키야키", "양꼬치", "마라탕", "마라샹궈", "모든회", "매운탕", "조개구이", "낙지볶음", "오징어볶음", "스테이크", "파스타", "연어회", "파전", "육회"]
        starbucks_menu = ["카페 아메리카노", "카페 라떼", "스타벅스 돌체 라떼", "카라멜 마키아또", "화이트 초콜릿 모카", "카페 모카", "바닐라 플랫 화이트", "에스프레소", "에스프레소 마키아또", "에스프레소 콘 파나", "자바 칩 프라푸치노", "초콜릿 크림 칩 프라푸치노", "제주 말차 크림 프라푸치노", "바닐라 크림 프라푸치노", "카라멜 프라푸치노", "피치 딸기 피지오", "쿨 라임 피지오", "블랙 티 레모네이드 피지오", "패션 탱고 티 레모네이드 피지오", "자몽 허니 BLACK 티", "유자 민트 티", "민트 BLENDED 티", "캐모마일 블렌드 티", "얼 그레이 티", "잉글리쉬 브렉퍼스트 티", "딸기 딜라이트 요거트 BLENDED", "망고 바나나 BLENDED", "에스프레소 프라푸치노", "더블 에스프레소 칩 프라푸치노", "제주 유기농 말차로 만든 라떼"]
        
        if "점메추" in text: await update.message.reply_text(f"☀️ 오늘 점심 메뉴는 {random.choice(lunch_menu)} 어떠세요?")
        elif "저메추" in text: await update.message.reply_text(f"🌙 오늘 저녁 메뉴는 {random.choice(dinner_menu)} 어떠세요?")
        elif "커추" in text: await update.message.reply_text(f"☕️ 스타벅스 추천 메뉴는 {random.choice(starbucks_menu)} 입니다.")
        return

    if text.startswith(('/출첵', '!출첵', '/출석체크', '!출석체크')):
        user_msg_id = update.message.message_id
        user_record = col_scores.find_one({"chat_id": str(chat_id), "user_id": str(uid), "game": "snake"})
        current_score = user_record["score"] if user_record else 0
        today_str = datetime.now(KST).strftime("%Y%m%d")
        last_check = user_record.get("last_check_date", "") if user_record else ""
        
        if last_check == today_str:
            err_msg = await update.message.reply_text(f"❌ {uname}님은 오늘 이미 출석체크를 완료하셨습니다.")
            if update.effective_chat.type != "private":
                asyncio.create_task(delete_messages_delayed(context, chat_id, [user_msg_id, err_msg.message_id], 3.0))
            return
            
        new_score = current_score + 1000
        col_scores.update_one({"chat_id": str(chat_id), "user_id": str(uid), "game": "snake"}, {"$set": {"user_name": uname, "score": new_score, "last_check_date": today_str}}, upsert=True)
        res_msg = await update.message.reply_text(f"✅ {uname}님 출석 완료! 1000 포인트가 지급되었습니다. 현재 보유 포인트: {new_score}")
        if update.effective_chat.type != "private":
            asyncio.create_task(delete_messages_delayed(context, chat_id, [user_msg_id, res_msg.message_id], 3.0))
        return

    if text.startswith(('/가족방최고', '!가족방최고')):
        user_msg_id = update.message.message_id
        r_chat_id = str(chat_id)
        
        if not box_event_rooms.get(r_chat_id, False):
            err_msg = await update.message.reply_text("💨 현재 이 방에 활성화된 연합상자가 없습니다. 다음 출현을 기다려주세요!")
            if update.effective_chat.type != "private":
                asyncio.create_task(delete_messages_delayed(context, chat_id, [user_msg_id, err_msg.message_id], 3.0))
            return
            
        box_event_rooms[r_chat_id] = False
        user_record = col_scores.find_one({"chat_id": r_chat_id, "user_id": str(uid), "game": "snake"})
        current_score = user_record["score"] if user_record else 0
        
        box_bonus = random.randint(300, 2000)
        new_score = current_score + box_bonus
        col_scores.update_one({"chat_id": r_chat_id, "user_id": str(uid), "game": "snake"}, {"$set": {"user_name": uname, "score": new_score}}, upsert=True)
        await update.message.reply_text(f"🎉 축하합니다! {uname}님이 선착순으로 연합상자를 획득하셨습니다! 무작위 보상 +{box_bonus} 포인트 지급 완료. 현재 방 포인트: {new_score}")
        return

    if text.startswith(('/대박', '!대박', '/중박', '!중박', '/소박', '!소박')):
        user_msg_id = update.message.message_id
        user_record = col_scores.find_one({"chat_id": str(chat_id), "user_id": str(uid), "game": "snake"})
        current_score = user_record["score"] if user_record else 0
        current_rolling = user_record.get("rolling_point", 0) if user_record else 0
        
        cost, win_chance, win_reward, gamble_type = 0, 0.0, 0, ""
        if text.startswith(('/대박', '!대박')): cost, win_chance, win_reward, gamble_type = 2000, 0.40, 4000, "대박"
        elif text.startswith(('/중박', '!중박')): cost, win_chance, win_reward, gamble_type = 1000, 0.45, 2000, "중박"
        elif text.startswith(('/소박', '!소박')): cost, win_chance, win_reward, gamble_type = 500, 0.45, 1000, "소박"

        if gamble_type:
            if current_score < cost:
                err_msg = await update.message.reply_text(f"❌ 보유 포인트가 부족하여 {gamble_type} 배팅에 참여할 수 없습니다. 최소 {cost} 포인트가 필요합니다. 현재 보유 포인트: {current_score}")
                asyncio.create_task(delete_messages_delayed(context, chat_id, [user_msg_id, err_msg.message_id], 3.0))
                return
                
            current_score -= cost
            rolling_bonus = int(cost * 0.01)
            new_rolling = current_rolling + rolling_bonus
            
            if random.random() < win_chance:
                current_score += win_reward
                msg_text = f"🔥 {uname}님 {gamble_type} 성공! 배당 2배인 {win_reward} 포인트를 획득했습니다!\n현재 보유 포인트: {current_score}점\n💰 누적 롤링 포인트: {new_rolling} P (+{rolling_bonus})"
            else:
                msg_text = f"💀 {uname}님 쪽박입니다 배팅포인트를 잃었습니다.\n현재 보유 포인트: {current_score}점\n💰 누적 롤링 포인트: {new_rolling} P (+{rolling_bonus})"
                
            col_scores.update_one({"chat_id": str(chat_id), "user_id": str(uid), "game": "snake"}, {"$set": {"user_name": uname, "score": current_score, "rolling_point": new_rolling}}, upsert=True)
            res_msg = await update.message.reply_text(msg_text)
            if update.effective_chat.type != "private":
                asyncio.create_task(delete_messages_delayed(context, chat_id, [user_msg_id, res_msg.message_id], 3.0))
            return

    # [실시간 야구장 타겟팅 기상 모듈] 범위형 유연 스캔 엔진 패치 완료판
    if text.startswith(('/날씨', '!날씨')):
        if not WEATHER_API_KEY: return await update.message.reply_text("⚠️ 날씨 API 키가 설정되지 않았습니다.")
        status_msg = await update.message.reply_text("🛰 <b>한·일 전 구장 예보 데이터 취합 중...</b>", parse_mode="HTML")
        w_ko = {"clear": "☀️맑음", "clouds": "☁️흐림", "rain": "🌧비", "drizzle": "🌦이슬비", "thunderstorm": "⛈폭우", "snow": "❄️눈", "mist": "🌫안개", "smoke": "🌫연기", "haze": "🌫박무"}
        
        msg = f"⚾️ <b>한·일 프로야구장 시간별 기상 요약 브리핑</b>\n🗓 기준일: {datetime.now(KST).strftime('%m월 %d일')}\n⏱ 분석 타임라인: 오후 13:00 ~ 저녁 20:00\n\n"
        for league, list_stadiums in STADIUMS.items():
            msg += f"■ <b>{league}</b>\n"
            for s_name, coord in list_stadiums.items():
                try:
                    url = f"http://api.openweathermap.org/data/2.5/forecast?lat={coord['lat']}&lon={coord['lon']}&appid={WEATHER_API_KEY}&units=metric"
                    res = requests.get(url, timeout=8).json()
                    if str(res.get("cod")) != "200":
                        msg += f"• {s_name}: 데이터 유실\n"; continue
                    
                    timeline_forecasts, today_str = [], datetime.now(KST).strftime("%Y-%m-%d")
                    dome_tag = " [돔]" if "돔" in s_name else ""
                    
                    for item in res.get("list", []):
                        dt_kst = datetime.fromtimestamp(item['dt'], tz=timezone.utc).astimezone(KST)
                        if dt_kst.strftime("%Y-%m-%d") == today_str and (11 <= dt_kst.hour <= 21):
                            sky_ko = w_ko.get(item['weather'][0]['main'].lower(), item['weather'][0]['main'].lower())
                            timeline_forecasts.append(f"{dt_kst.hour}시({sky_ko},{round(item['main']['temp'], 1)}℃)")
                    
                    if timeline_forecasts: msg += f"• <b>{s_name}{dome_tag}</b>\n  └ {', '.join(timeline_forecasts)}\n"
                    else:
                        tomorrow_str = (datetime.now(KST) + timedelta(days=1)).strftime("%Y-%m-%d")
                        for item in res.get("list", []):
                            dt_kst = datetime.fromtimestamp(item['dt'], tz=timezone.utc).astimezone(KST)
                            if dt_kst.strftime("%Y-%m-%d") == tomorrow_str and (11 <= dt_kst.hour <= 21):
                                sky_ko = w_ko.get(item['weather'][0]['main'].lower(), item['weather'][0]['main'].lower())
                                timeline_forecasts.append(f"{dt_kst.hour}시({sky_ko},{round(item['main']['temp'], 1)}℃)")
                        if timeline_forecasts: msg += f"• <b>{s_name}{dome_tag} (내일)</b>\n  └ {', '.join(timeline_forecasts)}\n"
                        else: msg += f"• <b>{s_name}{dome_tag}</b>\n  └ ☀️맑음(24℃) 기상 안정\n"
                except: msg += f"• {s_name}: 연동 지연\n"
            msg += "\n"
        await status_msg.delete(); await update.message.reply_text(msg, parse_mode="HTML")
        return

    # [개인 대화방 관리자 전용] 초간단 원터치 수식 연산 제어 엔진 (+유저ID 포인트 / -유저ID 포인트)
    if uid in ADMIN_LIST and update.effective_chat.type == "private":
        if text.startswith(('/점수차감', '/차감', '/포인트지급', '/지급', '+포인트', '+', '-')):
            parts = text.split()
            if (text.startswith('+') or text.startswith('-')) and not text.startswith('+포인트'):
                match_short = re.match(r'^([+-])\s*(\d+)\s+(\d+)$', text)
                if match_short:
                    cmd_sign, target_uid = match_short.group(1), match_short.group(2).strip()
                    try: val = int(match_short.group(3).strip())
                    except: return await update.message.reply_text("⚠️ 변경할 포인트는 반드시 정수 숫자로 입력하세요")
                else: return await update.message.reply_text("⚠️ 초간단 수식 형식\n지급: +유저아이디 포인트숫자\n차감: -유저아이디 포인트숫자\n\n예시: +8472713103 1000")
            else:
                if len(parts) < 3: return await update.message.reply_text("⚠️ 형식\n차감: /차감 유저아이디 차감숫자\n지급: +포인트 유저아이디 지급숫자")
                cmd_sign, target_uid = parts[0], parts[1].strip()
                try: val = int(parts[2].strip())
                except: return await update.message.reply_text("⚠️ 변경할 포인트는 반드시 정수 숫자로 입력하세요")

            sess = col_sessions.find_one({"admin_id": uid})
            t_id = sess['target_chat_id'] if sess else None
            if not t_id: return await update.message.reply_text("⚠️ /설정 명령어로 포인트를 조작할 방을 먼저 활성화해 주세요.")
            
            room_info = col_members.find_one({"chat_id": str(t_id)})
            mapped_name = room_info.get("users", {}).get(target_uid, "신규유저") if room_info else "신규유저"
            target_record = col_scores.find_one({"chat_id": str(t_id), "user_id": target_uid, "game": "snake"})
            old_score = target_record.get("score", 0) if target_record else 0
            act_user_name = target_record.get("user_name", mapped_name) if target_record else mapped_name
            
            if cmd_sign in ['/점수차감', '/차감', '-']: new_score, act_name = old_score - val, "차감"
            else: new_score, act_name = old_score + val, "지급"
                
            col_scores.update_one({"chat_id": str(t_id), "user_id": target_uid, "game": "snake"}, {"$set": {"user_name": act_user_name, "score": new_score}}, upsert=True)
            await update.message.reply_text(f"📉 포인트 {act_name} 완료. 대상유저: {act_user_name}님\n기존 포인트: {old_score}점 → 변경 포인트: {new_score}점")
            return

    if text.startswith(('/설정', '/리스트', '/삭제')) and uid in ADMIN_LIST and update.effective_chat.type == "private":
        btns = [[InlineKeyboardButton("📁 공용 설정", callback_data="set_room:common")]]
        for r in list(col_members.find()):
            if "room_name" in r: btns.append([InlineKeyboardButton(f"🏠 {r['room_name']}", callback_data=f"set_room:{r['chat_id']}")])
        return await update.message.reply_text("📂 관리할 방 선택:", reply_markup=InlineKeyboardMarkup(btns))
        
    if uid in ADMIN_LIST and update.effective_chat.type == "private":
        raw_html = update.message.caption_html or update.message.text_html or ""
        if update.message.photo or "/personal" in raw_html.lower() or "/스케줄등록" in raw_html.lower():
            m_id = update.message.media_group_id or f"s_{update.message.message_id}"
            if update.message.photo:
                if m_id not in media_group_cache: media_group_cache[m_id] = {"ids": [], "caption": raw_html, "task": None}
                media_group_cache[m_id]["ids"].append(update.message.photo[-1].file_id)
                if media_group_cache[m_id]["task"]: media_group_cache[m_id]["task"].cancel()
                media_group_cache[m_id]["task"] = asyncio.create_task(save_logic_with_delay(chat_id, context, m_id))
            else: await save_logic_with_delay(chat_id, context, None, update.message)
            return

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

# Flask 웹 서버 및 엔드포인트 구역
flask_app = Flask(__name__)

@flask_app.route('/')
def home(): return "OK", 200

@flask_app.route('/sports/live')
def sports_live():
    return """<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>뜌리 실시간 스코어센터</title>
    <style>
        body, html { margin: 0; padding: 0; width: 100%; height: 100%; overflow: hidden; background: #151922; }
        #container-wrapper { width: 100%; height: 100%; position: relative; overflow: hidden; }
        iframe { width: 100%; border: none; position: absolute; top: 0; left: 0; transform-origin: top left; }
    </style>
</head>
<body>
    <div id="container-wrapper">
        <iframe id="live-frame" src="https://www.flashscore.co.kr/"></iframe>
    </div>
    <script>
        function adjustLayout() {
            const frame = document.getElementById('live-frame');
            const wrapper = document.getElementById('container-wrapper');
            const windowWidth = window.innerWidth;
            const isMobileDevice = ('ontouchstart' in window) || (navigator.maxTouchPoints > 0);
            
            if (isMobileDevice) {
                const mobileCut = 58;
                frame.style.transform = 'none';
                frame.style.width = '100%';
                frame.style.marginTop = `-${mobileCut}px`;
                frame.style.height = `calc(100% + ${mobileCut}px)`;
            } else {
                const pcCut = 120;
                const baseWidth = 1200;
                if (windowWidth < baseWidth) {
                    const scale = windowWidth / baseWidth;
                    frame.style.width = baseWidth + 'px';
                    frame.style.height = ((wrapper.clientHeight / scale) + pcCut) + 'px';
                    frame.style.transform = `scale(${scale})`;
                    frame.style.marginTop = `-${pcCut}px`;
                } else {
                    frame.style.width = '100%';
                    frame.style.height = `calc(100% + ${pcCut}px)`;
                    frame.style.transform = 'none';
                    frame.style.marginTop = `-${pcCut}px`;
                }
            }
        }
        window.addEventListener('load', adjustLayout);
        window.addEventListener('resize', adjustLayout);
    </script>
</body>
</html>"""

@flask_app.route('/game/snake')
def snake_game():
    return """<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>뜌리 레트로 스네이크</title>
    <style>
        body { margin: 0; background: #111; color: #fff; text-align: center; font-family: sans-serif; overflow: hidden; }
        canvas { background: #222; display: block; margin: 15px auto; border: 4px solid #444; max-width: 90vw; aspect-ratio: 1; }
        #score { font-size: 24px; font-weight: bold; margin-top: 10px; color: #ffcc00; }
        .pad-container { display: grid; grid-template-columns: repeat(3, 60px); grid-template-rows: repeat(3, 60px); gap: 8px; justify-content: center; margin-top: 10px; }
        .pad-btn { background: #444; border: none; border-radius: 10px; color: #fff; font-size: 24px; font-weight: bold; display: flex; align-items: center; justify-content: center; user-select: none; -webkit-user-select: none; }
        .pad-btn:active { background: #ffcc00; color: #111; }
        .hide { visibility: hidden; }
    </style>
</head>
<body>
    <div id="score">SCORE: 0</div>
    <canvas id="gameCanvas" width="400" height="400"></canvas>
    <div class="pad-container">
        <div class="pad-btn hide"></div>
        <div class="pad-btn" id="btn-up">▲</div>
        <div class="pad-btn hide"></div>
        <div class="pad-btn" id="btn-left">◀</div>
        <div class="pad-btn hide"></div>
        <div class="pad-btn" id="btn-right">▶</div>
        <div class="pad-btn hide"></div>
        <div class="pad-btn" id="btn-down">▼</div>
        <div class="pad-btn hide"></div>
    </div>
    <script>
        const urlParams = new URLSearchParams(window.location.search);
        const chat_id = urlParams.get('chat_id') || '';
        const user_id = urlParams.get('user_id') || '';
        const user_name = urlParams.get('user_name') || '유저';
        const canvas = document.getElementById("gameCanvas"); const ctx = canvas.getContext("2d");
        const grid = 20; let score = 0; let count = 0;
        let snake = { x: 160, y: 160, dx: grid, dy: 0, cells: [{x: 160, y: 160}, {x: 140, y: 160}], maxCells: 2 };
        let apple = { x: 320, y: 320 };
        function getRandomInt(min, max) { return Math.floor(Math.random() * (max - min)) + min; }
        function sendScore(finalScore) {
            if(!chat_id || !user_id) return;
            fetch('/game/submit_score', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ chat_id: chat_id, user_id: user_id, user_name: user_name, score: finalScore, game: 'snake' })
            });
        }
        function resetGame() {
            sendScore(score); score = 0; document.getElementById("score").innerText = "SCORE: " + score;
            snake.x = 160; snake.y = 160; snake.cells = [{x: 160, y: 160}, {x: 140, y: 160}];
            snake.maxCells = 2; snake.dx = grid; snake.dy = 0;
            apple.x = getRandomInt(0, 20) * grid; apple.y = getRandomInt(0, 20) * grid;
        }
        function loop() {
            requestAnimationFrame(loop); if (++count < 6) { return; } count = 0; ctx.clearRect(0,0,canvas.width,canvas.height);
            snake.x += snake.dx; snake.y += snake.dy;
            if (snake.x < 0 || snake.x >= canvas.width || snake.y < 0 || snake.y >= canvas.height) { resetGame(); }
            snake.cells.unshift({x: snake.x, y: snake.y}); if (snake.cells.length > snake.maxCells) { snake.cells.pop(); }
            ctx.fillStyle = '#ff4444'; ctx.fillRect(apple.x, apple.y, grid-1, grid-1); ctx.fillStyle = '#ffcc00';
            snake.cells.forEach(function(cell, index) {
                ctx.fillRect(cell.x, cell.y, grid-1, grid-1);  
                if (cell.x === apple.x && cell.y === apple.y) {
                    snake.maxCells++; score += 10; document.getElementById("score").innerText = "SCORE: " + score;
                    apple.x = getRandomInt(0, 20) * grid; apple.y = getRandomInt(0, 20) * grid;
                }
                for (let i = index + 1; i < snake.cells.length; i++) { if (cell.x === snake.cells[i].x && cell.y === snake.cells[i].y) { resetGame(); } }
            });
        }
        document.addEventListener('keydown', function(e) {
            if (e.which === 37 && snake.dx === 0) { snake.dx = -grid; snake.dy = 0; }
            else if (e.which === 38 && snake.dy === 0) { snake.dy = -grid; snake.dx = 0; }
            else if (e.which === 39 && snake.dx === 0) { snake.dx = grid; snake.dy = 0; }
            else if (e.which === 40 && snake.dy === 0) { snake.dy = grid; snake.dx = 0; }
        });
        document.getElementById('btn-up').addEventListener('touchstart', () => { if(snake.dy === 0) { snake.dy = -grid; snake.dx = 0; } });
        document.getElementById('btn-down').addEventListener('touchstart', () => { if(snake.dy === 0) { snake.dy = grid; snake.dx = 0; } });
        document.getElementById('btn-left').addEventListener('touchstart', () => { if(snake.dx === 0) { snake.dx = -grid; snake.dy = 0; } });
        document.getElementById('btn-right').addEventListener('touchstart', () => { if(snake.dx === 0) { snake.dx = grid; snake.dy = 0; } });
        document.getElementById('btn-up').addEventListener('mousedown', () => { if(snake.dy === 0) { snake.dy = -grid; snake.dx = 0; } });
        document.getElementById('btn-down').addEventListener('mousedown', () => { if(snake.dy === 0) { snake.dy = grid; snake.dx = 0; } });
        document.getElementById('btn-left').addEventListener('mousedown', () => { if(snake.dx === 0) { snake.dx = -grid; snake.dy = 0; } });
        document.getElementById('btn-right').addEventListener('mousedown', () => { if(snake.dx === 0) { snake.dx = grid; snake.dy = 0; } });
        window.addEventListener('touchmove', (e) => { e.preventDefault(); }, { passive: false });
        requestAnimationFrame(loop);
    </script>
</body>
</html>"""

@flask_app.route('/game/submit_score', methods=['POST'])
def submit_score():
    data = request.json
    if not data: return jsonify({"status": "error"}), 400
    chat_id, user_id, user_name, score, game_type = str(data.get('chat_id')), str(data.get('user_id')), data.get('user_name', '유저'), int(data.get('score', 0)), data.get('game', 'brick')
    col_scores.update_one({"chat_id": chat_id, "user_id": user_id, "game": game_type}, {"$set": {"user_name": user_name}, "$max": {"score": score}}, upsert=True)
    return jsonify({"status": "success"}), 200

def run_flask():
    flask_app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)))

async def post_init(application):
    await userbot.start()
    asyncio.create_task(custom_scheduler_loop(application))

if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    app = ApplicationBuilder().token(TOKEN).post_init(post_init).build()
    app.add_handler(MessageHandler(filters.ALL, handle_message))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.run_polling()
