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

# 배팅 엔진 전용 핵심 컬렉션
col_bets = mongodb['active_bets']
col_user_bets = mongodb['user_bets']

# 전역 상태 및 가변 타이머 캐시 제어용
box_event_rooms = {}
bet_timer_tasks = {}  # 방별 자동 마감 비동기 태스크 저장 슬롯

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

userbot = TelegramClient(StringSession(STRING_SESSION), API_ID, API_HASH)
media_group_cache = {}

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

# 💡 [신규 엔진] 숫자/기호 프리미엄 이모지 변환기 (7강 이상 전용)
def get_num_emoji(text):
    emoji_map = {
        '+': '6206427772231881680',
        '0': '6206046812927693478',
        '1': '6208774722751041537',
        '2': '6208469659813941908',
        '3': '6208545800994165306',
        '4': '6206366337019678906',
        '5': '6206061815248458530',
        '6': '6208748330177007798',
        '7': '6208316076078404760',
        '8': '6208747050276754444',
        '9': '6208737932061184858'
    }
    res = ""
    for char in text:
        if char in emoji_map:
            res += f'<tg-emoji emoji-id="{emoji_map[char]}">{char}</tg-emoji>'
        else:
            res += char
    return res

# 💡 [정밀 수정 엔진] 이모지 파싱 오류 완벽 차단용
def get_e_tag(e_lv):
    if e_lv <= 0: 
        return ""
    
    # 이모지 ID를 텔레그램이 인식하도록 태그 구조 재설계
    def t(eid, txt):
        return f'<tg-emoji emoji-id="{eid}">{txt}</tg-emoji>'

    if e_lv <= 2: 
        return f"<b>[+{e_lv}]</b> "
    elif e_lv == 3: 
        return f"🔷<code>[+{e_lv}]</code> "
    elif e_lv == 4: 
        return f"{t('5359528850743108099', '🔷')}<code>[+{e_lv}]</code> "
    elif e_lv == 5: 
        return f"{t('5359284999679910348', '🔥')}<b>【+{e_lv}】</b>{t('5359284999679910348', '🔥')} "
    elif e_lv == 6: 
        return f"{t('5402406965252989103', '🔮')}<code><b>[+{e_lv}]</b></code> "
    elif e_lv == 7: 
        n = get_num_emoji(f"+{e_lv}")
        return f"{t('5361895016945950643', '🌟')}<b>【{n}】</b> "
    elif e_lv == 8: 
        n = get_num_emoji(f"+{e_lv}")
        return f"{t('5431776939465516694', '💎')}<b>【{n}】</b> "
    elif e_lv == 9: 
        n = get_num_emoji(f"+{e_lv}")
        return f"{t('5433758796289685818', '👑')}<b>꧁{n}꧂</b> "
    else: 
        n = get_num_emoji(f"+{e_lv}")
        p = t('5359653443449399145', '✨') + t('5361979846845014099', '✨') + t('5359477766402090098', '✨')
        return f"{p}<b>꧁༺{n}༻꧂</b> "

async def check_auth(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid in ADMIN_LIST: return True
    if update.effective_chat.type == "private": return False
    try:
        member = await context.bot.get_chat_member(update.effective_chat.id, uid)
        return member.status in ["administrator", "creator"]
    except: return False

async def delete_messages_delayed(context: ContextTypes.DEFAULT_TYPE, chat_id: int, message_ids: list, delay: float = 3.0):
    await asyncio.sleep(delay)
    for msg_id in message_ids:
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=msg_id)
        except Exception as e:
            logging.error(f"메시지 자동 삭제 실패 (ID: {msg_id}): {e}")

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

async def custom_scheduler_loop(application):
    global box_event_rooms
    await asyncio.sleep(10)
    bot = application.bot
    next_box_ts = datetime.now(KST).timestamp() + random.randint(30, 55) * 60
    while True:
        try:
            now = datetime.now(KST)
            now_ts = now.timestamp()
            now_date, now_time = now.strftime("%Y%m%d"), now.strftime("%H%M")
            if now_ts >= next_box_ts:
                next_box_ts = now_ts + random.randint(30, 55) * 60
                for r in list(col_members.find()):
                    r_chat_id = str(r['chat_id'])
                    box_event_rooms[r_chat_id] = True
                    try:
                        await bot.send_message(chat_id=int(r_chat_id), text="<tg-emoji emoji-id=\"5406929905118106968\">📦</tg-emoji> <b>연합상자가 출현했습니다!</b>\n /가족방최고 혹은 !가족방최고 를 먼저 쳐주신 1분에게 랜덤 포인트를 지급합니다!", parse_mode="HTML")
                    except: pass
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
        await asyncio.sleep(10)

async def bet_reservation_worker(bot, chat_id, target_dt):
    try:
        now = datetime.now(KST)
        delay = (target_dt - now).total_seconds()
        if delay > 0:
            await asyncio.sleep(delay)
        res = col_bets.update_one({"chat_id": str(chat_id)}, {"$set": {"status": "closed"}})
        if res.modified_count > 0:
            await bot.send_message(chat_id=int(chat_id), text="🔒 <b>예약 마감 타이머가 만료되었습니다.</b>\n지정한 경기 시간이 되어 본 방의 투표판이 동결 마감되었습니다.", parse_mode="HTML")
    except asyncio.CancelledError:
        logging.info(f"방 [{chat_id}] 예약마감 타이머가 관리자에 의해 덮어쓰기 취소되었습니다.")
    except Exception as e:
        logging.error(f"예약마감 작동 에러: {e}")

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
            if not match: raise ValueError("스케줄 등록 형식이 올바르지 않습니다")
            name, start_dt, end_dt, time_range, interval = clean_tags(match.group(1)), clean_tags(match.group(2)), clean_tags(match.group(3)), clean_tags(match.group(4)), int(match.group(5))
            content = match.group(6).strip()
            time_parts = re.split(r'[~-]', time_range)
            slot_start = re.sub(r'[^0-9]', '', time_parts[0]).zfill(4) if len(time_parts) >= 2 else re.sub(r'[^0-9]', '', time_range)[:4]
            slot_end = re.sub(r'[^0-9]', '', time_parts[1]).zfill(4) if len(time_parts) >= 2 else re.sub(r'[^0-9]', '', time_range)[-4:]
            now_ts = datetime.now(KST).timestamp()
            data = {"chat_id": t_id, "name": name, "start_dt": start_dt, "end_dt": end_dt, "slot_start": slot_start, "slot_end": slot_end, "interval": interval, "next_run_ts": now_ts + interval * 60, "data": {"photos": (media_group_cache[m_id]["ids"] if m_id else []), "caption": balance_html(content)}}
            col_sched.insert_one(data); await context.bot.send_message(chat_id, f"⏰ {name} 예약 완료")
        elif "/personal" in cleaned_lower:
            m = re.search(r"/personal\s+(\S+)\s*(.*)", cleaned, re.DOTALL)
            if not m: raise ValueError("형식 오류")
            key, content = clean_tags(m.group(1)), m.group(2)
            msg, btn = content.rsplit("---", 1) if "---" in content else (content, "")
            cmd_data = {"photos": (media_group_cache[m_id]["ids"] if m_id else []), "caption": balance_html(msg.strip()), "buttons": re.sub('<[^<]+?>', '', btn).strip()}
            if t_id == "common": col_main.update_one({"id": "bot_main_data"}, {"$set": {f"commands.{key}": cmd_data}}, upsert=True)
            else: col_members.update_one({"chat_id": t_id}, {"$set": {f"local_commands.{key}": cmd_data}}, upsert=True)
            await context.bot.send_message(chat_id, f"✅ {key} 저장 완료")
    except Exception as e: await context.bot.send_message(chat_id, f"❌ 에러 발생 {clean_tags(str(e))}")
    if m_id in media_group_cache: del media_group_cache[m_id]

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global box_event_rooms, bet_timer_tasks
    if not update.message: return
    uid, text, chat_id = update.effective_user.id, (update.message.text or "").strip(), update.effective_chat.id
    uname = update.effective_user.first_name
    
    # 📌 [관리자 전용: 전 유저 도박 횟수 당장 강제 리셋]
    if uid in ADMIN_LIST and text == "/도박초기화":
        col_scores.update_many({}, {"$set": {"today_daebak_count": 0, "today_jungbak_count": 0, "today_sobak_count": 0, "last_gamble_date": ""}})
        return await update.message.reply_text("✅ <b>[DB 청소 완료]</b>\n전 유저의 도박 횟수가 지금 당장 강제 0으로 리셋되었습니다!", parse_mode="HTML")
        
    # 📌 [뱅킹 모듈 위치 고정]
    if uid in ADMIN_LIST:
        target_uid, change_amt, is_matched = None, 0, False
        text_clean = text.replace(',', '').strip()
        
        if text_clean.upper().startswith(('/지급', '/차감', '/점수차감', '/포인트지급')):
            parts = text_clean.split()
            if len(parts) >= 3 and parts[1].isdigit() and parts[2].isdigit():
                target_uid = parts[1]
                change_amt = int(parts[2]) if ('지급' in parts[0]) else -int(parts[2])
                is_matched = True
                
        elif text_clean.startswith(('+', '-', '—', '–')) and not text_clean.upper().startswith('+포인트'):
            sign = '+' if text_clean.startswith('+') else '-'
            stripped_text = re.sub(r'^.*?(\d+)\s+(\d+).*$', r'\1 \2', text_clean)
            parts = stripped_text.split()
            if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
                target_uid = parts[0]
                change_amt = int(parts[1]) if sign == '+' else -int(parts[1])
                is_matched = True
        
        if is_matched:
            if update.effective_chat.type == "private":
                sess = col_sessions.find_one({"admin_id": uid})
                target_cid = sess['target_chat_id'] if sess and 'target_chat_id' in sess else None
                if not target_cid or target_cid == "common":
                    return await update.message.reply_text("⚠️ /설정 명령어로 먼저 대상 방을 선택해주세요.")
            else:
                target_cid = str(chat_id)
            
            u_rec = col_scores.find_one({"chat_id": target_cid, "user_id": str(target_uid), "game": "snake"})
            new_p = max(0, (u_rec['score'] if u_rec else 0) + change_amt)
            col_scores.update_one(
                {"chat_id": target_cid, "user_id": str(target_uid), "game": "snake"}, 
                {"$set": {"score": new_p}, "$setOnInsert": {"user_name": f"유저({target_uid})"}}, 
                upsert=True
            )
            return await update.message.reply_text(f"⚡️ <b>[포인트 조절 완료]</b>\n• 방ID: <code>{target_cid}</code>\n• 유저: <code>{target_uid}</code>\n• 변동: {change_amt:+,} P\n• 잔고: {new_p:,} P", parse_mode="HTML")

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

    if text.startswith('/유저조회'):
        if uid not in ADMIN_LIST or update.effective_chat.type != "private": return
        sess = col_sessions.find_one({"admin_id": uid})
        t_id = sess['target_chat_id'] if sess else None
        if not t_id: return await update.message.reply_text("⚠️ /설정 명령어로 방 선택 먼저 하세요.")
        room = col_members.find_one({"chat_id": t_id})
        if not room: return await update.message.reply_text("❌ 방 정보 없음")
        users = room.get("users", {})
        joined_users = {str(r['user_id']): r['user_name'] for r in col_scores.find({"chat_id": str(t_id)})}
        msg = f"👥 <b>{room.get('room_name')} 유저 참여 현황</b>\n\n"
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
            await msg.edit_text(f"✅ 완료 {len(users)}명")
            return
        if text.startswith(("/all", "/전체공지")):
            room = col_members.find_one({"chat_id": str(chat_id)})
            m_list = list(room.get("users", {}).items()) if room else []
            if not m_list: return await update.message.reply_text("❌ 동기화 먼저 진행")
            for i in range(0, len(m_list), 10):
                mentions = [f"<a href='tg://user?id={mid}'>{mname}</a>" for mid, mname in m_list[i:i+10]]
                await context.bot.send_message(chat_id, " ".join(mentions), parse_mode="HTML")
                await asyncio.sleep(1.2)
            return

    if text.startswith(('/랭킹', '!랭킹', '/ranking', '!ranking')):
        point_records = list(col_scores.find({"chat_id": str(chat_id), "game": "snake"}).sort("score", -1).limit(10))
        msg = "🏆 <b>실시간 포인트 TOP 10</b>\n\n"
        for idx, r in enumerate(point_records, 1):
            e_lv = r.get("enhancement_level", 0)
            e_tag = get_e_tag(e_lv)
            
            # [방어 코드] 닉네임 내의 특수문자(<, >, & 등)를 HTML 안전 문자로 변환
            raw_name = r.get('user_name', '유저')
            safe_name = html.escape(raw_name) 
            
            # [조건부 진하게] 6강 이상 시 <b> 태그 적용
            d_name = f"<b>{safe_name}</b>" if e_lv >= 6 else safe_name
            
            msg += f" {idx}위 : {e_tag}{d_name} - {r.get('score', 0):,}P\n"
        
        # [방어 코드] 메시지가 너무 길거나 태그 오류로 HTML 전송 실패 시, parse_mode 없이 plain text로 재시도
        try:
            await update.message.reply_text(msg, parse_mode="HTML")
        except Exception as e:
            logging.error(f"HTML 파싱 에러 발생, Plain Text로 전송 시도: {e}")
            await update.message.reply_text(clean_tags(msg)) # 태그 다 떼고 전송
        return

    # 💰 [유저 전용: 내 포인트 및 잔고 조회]
    if text.startswith(('/내포인트', '!내포인트', '/잔고', '!잔고', '/포인트', '!포인트')):
        user_record = col_scores.find_one({"chat_id": str(chat_id), "user_id": str(uid), "game": "snake"})
        current_score = user_record.get("score", 0) if user_record else 0
        e_lv = user_record.get("enhancement_level", 0) if user_record else 0
        
        # 0강일 때도 [+0]이 보이도록 강제 처리
        e_tag_display = get_e_tag(e_lv).strip() if e_lv > 0 else "<b>[+0]</b>"
        d_name = f"<b>{uname}</b>" if e_lv >= 6 else uname
        
        msg = (
            f"💳 {e_tag_display} {d_name}님의 계좌 상태\n\n"
            f"💰 <b>현재 잔고:</b> {current_score:,} P\n"
            f"🎖 <b>강화 칭호:</b> +{e_lv} (모든 획득 포인트 +{e_lv}% 보너스)\n"
        )
        return await update.message.reply_text(msg, parse_mode="HTML")

    # 🌟 [유저 전용: 칭호 강화 시스템 (10단계 확률/비용 커스텀 적용)]
    if text.startswith(('/강화', '!강화')):
        user_msg_id = update.message.message_id
        user_record = col_scores.find_one({"chat_id": str(chat_id), "user_id": str(uid), "game": "snake"})
        if not user_record:
            err = await update.message.reply_text("⚠️ 포인트 데이터가 없습니다. 출석체크 등으로 포인트를 먼저 획득하세요.")
            if update.effective_chat.type != "private": asyncio.create_task(delete_messages_delayed(context, chat_id, [user_msg_id, err.message_id], 3.0))
            return
        
        c_score = user_record.get("score", 0)
        e_lv = user_record.get("enhancement_level", 0)
        
        if e_lv >= 17:
            err = await update.message.reply_text(f"🛑 <b>[MAX 레벨 도달]</b>\n이미 최고 레벨(+17)입니다. 더 이상 강화할 수 없습니다.", parse_mode="HTML")
            if update.effective_chat.type != "private": asyncio.create_task(delete_messages_delayed(context, chat_id, [user_msg_id, err.message_id], 3.0))
            return
            
        cost, prob = 0, 0.0
        # 형님이 요청하신 확률 및 비용 밸런스 매핑
        if e_lv == 0: cost, prob = 5000, 0.45     # 0 -> 1강 (45%)
        elif e_lv == 1: cost, prob = 5000, 0.45   # 1 -> 2강 (45%)
        elif e_lv == 2: cost, prob = 5000, 0.40   # 2 -> 3강 (40%)
        elif e_lv == 3: cost, prob = 5000, 0.40   # 3 -> 4강 (40%)
        elif e_lv == 4: cost, prob = 5000, 0.35   # 4 -> 5강 (35%)
        elif e_lv == 5: cost, prob = 10000, 0.20  # 5 -> 6강 (20%)
        elif e_lv == 6: cost, prob = 10000, 0.20  # 6 -> 7강 (20%)
        elif e_lv == 7: cost, prob = 10000, 0.10  # 7 -> 8강 (10%)
        elif e_lv == 8: cost, prob = 10000, 0.10  # 8 -> 9강 (10%)
        elif e_lv == 9: cost, prob = 30000, 0.02  # 9 -> 10강 (2%)
        elif e_lv == 10: cost, prob = 30000, 0.05  # 10 -> 11강 (5%)
        elif e_lv == 11: cost, prob = 30000, 0.05  # 11 -> 12강 (5%)
        elif e_lv == 12: cost, prob = 30000, 0.05  # 12 -> 13강 (5%)
        elif e_lv == 13: cost, prob = 30000, 0.05  # 13 -> 14강 (5%)
        elif e_lv == 14: cost, prob = 30000, 0.05  # 14 -> 15강 (5%)
        elif e_lv == 15: cost, prob = 30000, 0.05  # 15 -> 16강 (5%)
        elif e_lv == 16: cost, prob = 30000, 0.05  # 16 -> 17강 (5%)
            
        # 👑 [특별 혜택: 지정 유저 강화 확률 1.5배 비밀 버프]
        if uid in [7380985690, 7966676973]:
            prob = prob * 1.5
        
        if c_score < cost:
            err = await update.message.reply_text(f"❌ <b>강화 실패 (포인트 부족)</b>\n현재 [+{e_lv}] -> [+{e_lv+1}] 시도에는 {cost:,} P가 필요합니다.\n💳 잔고: {c_score:,} P", parse_mode="HTML")
            if update.effective_chat.type != "private": asyncio.create_task(delete_messages_delayed(context, chat_id, [user_msg_id, err.message_id], 3.0))
            return
            
        # 필수 액션 구간 (소모량 텍스트 제거 완료)
        c_score -= cost
        
        if random.random() < prob:
            e_lv += 1
            e_tag_new = get_e_tag(e_lv).strip()
            d_name = f"<b>{uname}</b>" if e_lv >= 6 else uname
            msg = f"🌟 <b>강화 성공!!!</b> 🌟\n\n🎉 {d_name}님의 칭호가 {e_tag_new}(으)로 강화되었습니다!\n(모든 획득 포인트 {e_lv}% 영구 증가)\n💳 잔고: {c_score:,} P"
        else:
            e_tag_old = get_e_tag(e_lv).strip() if e_lv > 0 else "<b>[+0]</b>"
            d_name = f"<b>{uname}</b>" if e_lv >= 6 else uname
            msg = f"💥 <b>강화 실패...</b> 💥\n\n아깝게 실패했습니다. 수치는 {e_tag_old}(으)로 유지됩니다.\n💳 잔고: {c_score:,} P"
            
        col_scores.update_one({"chat_id": str(chat_id), "user_id": str(uid), "game": "snake"}, {"$set": {"score": c_score, "enhancement_level": e_lv, "user_name": uname}}, upsert=True)
        res = await update.message.reply_text(msg, parse_mode="HTML")
        return

    if text.startswith(('/score', '!score', '/스코어', '!스코어')):
        url_live = f"https://dduri-bot.onrender.com/sports/live"
        keyboard = [[InlineKeyboardButton(text="📊 실시간 스포츠 스코어센터 진입", url=url_live)]]
        await update.message.reply_text("📣 <b>뜌리 라이브 스코어센터</b>\n\n아래 버튼을 누르면 기기별 크기에 최적화된 실시간 경기 상황판이 열립니다.", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
        return

    if text.startswith(('/점메추', '!점메추', '/저메추', '!저메추', '/커추', '!커추', '/야메추', '!야메추')):
        lunch_menu = ["김치찌개", "된장찌개", "부대찌개", "제육볶음", "돈까스", "짜장면", "짬뽕", "볶음밥", "탕수육", "김밥", "라면", "떡볶이", "순대", "순대국밥", "뼈해장국", "설렁탕", "갈비탕", "육개장", "비빔밥", "칼국수", "수제비", "물냉면", "비빔냉면", "우동", "초밥", "회덮밥", "파스타", "피자", "햄버거", "샌드위치"]
        dinner_menu = ["삼겹살", "돼지갈비", "소고기구이", "닭갈비", "치킨", "족발", "보쌈", "곱창구이", "막창구이", "곱창전골", "아구찜", "해물찜", "찜닭", "닭볶음탕", "감자탕", "샤브샤브", "스키야키", "양꼬치", "마라탕", "마라샹궈", "모듬회", "매운탕", "조개구이", "낙지볶음", "오징어볶음", "스테이크", "파스타", "연어회", "파전", "육회"]
        starbucks_menu = ["카페 아메리카노", "카페 라떼", "스타벅스 돌체 라떼", "카라멜 마키아또", "화이트 초콜릿 모카", "카페 모카", "바닐라 플랫 화이트", "에스프레소", "에스프레소 마키아또", "에스프레소 콘 파나", "자바 칩 프라푸치노", "초콜릿 크림 칩 프라푸치노", "제주 말차 크림 프라푸치노", "바닐라 크림 프라푸치노", "카라멜 프라푸치노", "피치 딸기 피지오", "쿨 라임 피지오", "블랙 티 레모네이드 피지오", "패션 탱고 티 레모네이드 피지오", "자몽 허니 블랙티", "유자 민트 티", "민트 블렌디드 티", "캐모마일 블렌드 티", "얼 그레이 티", "잉글리쉬 브렉퍼스트 티", "딸기 딜라이트 요거트 블렌디드", "망고 바나나 블렌디드", "에스프레소 프라푸치노", "더블 에스프레소 칩 프라푸치노", "제주 유기농 말차로 만든 라떼"]
        yasik_menu = ["후라이드 치킨", "매운 양념 치킨", "한방 온족발", "직화 불족발", "마늘 보쌈", "매콤 국물 닭발", "숯불 돼지껍데기", "찹쌀 탕수육", "직화 불막창", "돼지고기 짜글이", "페퍼로니 피자", "국물 떡볶이와 튀김", "한강 즉석 라면", "치즈 불닭", "오돌뼈와 주먹밥", "타코야끼", "계란말이와 골뱅이무침", "해물파전", "콘치즈와 모듬 소시지", "훈제 연어 샐러드"]
        if "점메추" in text: await update.message.reply_text(f"☀️ 오늘 점심 메뉴는 <b>{random.choice(lunch_menu)}</b> 어떠세요?", parse_mode="HTML")
        elif "저메추" in text: await update.message.reply_text(f"🌙 오늘 저녁 메뉴는 <b>{random.choice(dinner_menu)}</b> 어떠세요?", parse_mode="HTML")
        elif "커추" in text: await update.message.reply_text(f"☕️ 스타벅스 추천 메뉴는 <b>{random.choice(starbucks_menu)}</b> 입니다.", parse_mode="HTML")
        elif "야메추" in text: await update.message.reply_text(f"🔥 밤을 잊은 그대에게! 오늘 야식 메뉴는 <b>{random.choice(yasik_menu)}</b> 강력 추천합니다!", parse_mode="HTML")
        return

    # 🎲 [유저 전용 /대박, /중박, /소박 포인트 롤링 도박 구역 + 강화 보너스 적용]
    if text.startswith(('/대박', '!대박', '/중박', '!중박', '/소박', '!소박')):
        user_msg_id = update.message.message_id
        user_record = col_scores.find_one({"chat_id": str(chat_id), "user_id": str(uid), "game": "snake"})
        current_score = user_record.get("score", 0) if user_record else 0
        current_rolling = user_record.get("rolling_point", 0) if user_record else 0
        e_lv = user_record.get("enhancement_level", 0) if user_record else 0
        e_tag = get_e_tag(e_lv)
        bonus_pct = e_lv * 0.01
        
        now_kst = datetime.now(KST)
        today_str = now_kst.strftime("%Y%m%d")
        last_gamble_date = user_record.get("last_gamble_date", "") if user_record else ""
        is_new_day = (last_gamble_date != today_str)
        
        cost, win_chance, win_reward, gamble_type, count_field = 0, 0.0, 0, "", ""
        if text.startswith(('/대박', '!대박')): cost, win_chance, win_reward, gamble_type, count_field = 2000, 0.40, 4000, "대박", "today_daebak_count"
        elif text.startswith(('/중박', '!중박')): cost, win_chance, win_reward, gamble_type, count_field = 1000, 0.45, 2000, "중박", "today_jungbak_count"
        elif text.startswith(('/소박', '!소박')): cost, win_chance, win_reward, gamble_type, count_field = 500, 0.45, 1000, "소박", "today_sobak_count"

        if uid in [916176217, 7530073279]: 
            win_chance = win_chance * 0.8

        if uid in [7380985690]:
            win_chance = win_chance * 1.5
        
        if gamble_type:
            current_count = 0 if is_new_day else user_record.get(count_field, 0)
            d_name = f"<b>{uname}</b>" if e_lv >= 6 else uname
            
            if current_count >= 10:
                err_limit = await update.message.reply_text(f"🛑 {e_tag}{d_name}님, [{gamble_type}] 배팅은 하루 최대 10회까지만 참여 가능합니다.")
                if update.effective_chat.type != "private": asyncio.create_task(delete_messages_delayed(context, chat_id, [user_msg_id, err_limit.message_id], 3.0))
                return

            if current_score < cost:
                err_msg = await update.message.reply_text(f"❌ 보유 포인트가 부족하여 {gamble_type} 배팅에 참여할 수 없습니다. 최소 {cost} 포인트가 필요합니다. 현재 보유 포인트: {current_score:,} P")
                if update.effective_chat.type != "private": asyncio.create_task(delete_messages_delayed(context, chat_id, [user_msg_id, err_msg.message_id], 3.0))
                return
                
            current_score -= cost
            rolling_bonus = int(cost * 0.01)
            new_rolling = current_rolling + rolling_bonus
            new_count = current_count + 1
            
            if random.random() < win_chance:
                actual_win = int(win_reward * (1 + bonus_pct))
                b_gained = actual_win - win_reward
                current_score += actual_win
                b_txt = f"\n🌟 <b>강화 보너스: +{b_gained:,} P</b>" if b_gained > 0 else ""
                msg_text = f"🔥 {e_tag}{d_name}님 <b>{gamble_type} 성공! ({new_count}/10)</b>\n배당금 {actual_win:,} 포인트를 획득했습니다!{b_txt}\n💰 현재 보유 포인트: {current_score:,} P\n💎 누적 롤링 포인트: {new_rolling:,} P (+{rolling_bonus})"
            else:
                msg_text = f"💀 {e_tag}{d_name}님 <b>쪽박입니다. ({new_count}/10)</b>\n배팅포인트 {cost:,} P를 잃었습니다.\n💰 현재 보유 포인트: {current_score:,} P\n💎 누적 롤링 포인트: {new_rolling:,} P (+{rolling_bonus})"
                
            update_data = {
                "user_name": uname, 
                "score": current_score, 
                "rolling_point": new_rolling, 
                "last_gamble_date": today_str, 
                count_field: new_count
            }
            
            if is_new_day:
                if gamble_type != "대박": update_data["today_daebak_count"] = 0
                if gamble_type != "중박": update_data["today_jungbak_count"] = 0
                if gamble_type != "소박": update_data["today_sobak_count"] = 0
                
            col_scores.update_one(
                {"chat_id": str(chat_id), "user_id": str(uid), "game": "snake"}, 
                {"$set": update_data}, 
                upsert=True
            )
            
            res_msg = await update.message.reply_text(msg_text, parse_mode="HTML")
            if update.effective_chat.type != "private": asyncio.create_task(delete_messages_delayed(context, chat_id, [user_msg_id, res_msg.message_id], 4.5))
            return

    # 📅 [개조형 출석체크 엔진 + 강화 보너스 적용]
    if text.startswith(('/출첵', '!출첵', '/출석체크', '!출석체크')):
        user_msg_id = update.message.message_id
        user_record = col_scores.find_one({"chat_id": str(chat_id), "user_id": str(uid), "game": "snake"})
        current_score = user_record.get("score", 0) if user_record else 0
        e_lv = user_record.get("enhancement_level", 0) if user_record else 0
        e_tag = get_e_tag(e_lv)
        bonus_pct = e_lv * 0.01
        
        now_kst = datetime.now(KST)
        today_str = now_kst.strftime("%Y%m%d")
        yesterday_str = (now_kst - timedelta(days=1)).strftime("%Y%m%d")
        last_check = user_record.get("last_check_date", "") if user_record else ""
        current_streak = user_record.get("check_streak", 0) if user_record else 0
        d_name = f"<b>{uname}</b>" if e_lv >= 6 else uname
        
        if last_check == today_str:
            err_msg = await update.message.reply_text(f"❌ {e_tag}{d_name}님은 오늘 이미 출석체크를 완료하셨습니다. (현재 연속 {current_streak}일차)")
            if update.effective_chat.type != "private": asyncio.create_task(delete_messages_delayed(context, chat_id, [user_msg_id, err_msg.message_id], 3.0))
            return
            
        new_streak = current_streak + 1 if last_check == yesterday_str else 1
        bonus_msg, base_reward = "", 1000
        if new_streak == 30: 
            base_reward += 30000; new_streak = 0; bonus_msg = "\n🔥 <b>[대박] 30일 연속 출석 달성 보너스 +30,000 포인트 폭격 지급!</b>"
            
        actual_reward = int(base_reward * (1 + bonus_pct))
        b_gained = actual_reward - base_reward
        new_score = current_score + actual_reward
        
        col_scores.update_one({"chat_id": str(chat_id), "user_id": str(uid), "game": "snake"}, {"$set": {"user_name": uname, "score": new_score, "last_check_date": today_str, "check_streak": new_streak}}, upsert=True)
        b_txt = f" (🌟강화보너스 +{b_gained:,}P)" if b_gained > 0 else ""
        res_msg = await update.message.reply_text(f"✅ {e_tag}{d_name}님 출석 완료! {actual_reward:,}P 지급 완료! ({new_streak}일차){b_txt}{bonus_msg}\n💰 보유 잔고: {new_score:,} P", parse_mode="HTML")
        if update.effective_chat.type != "private": asyncio.create_task(delete_messages_delayed(context, chat_id, [user_msg_id, res_msg.message_id], 4.5))
        return

    # 📦 [수급 기능 2] 연합상자 + 강화 보너스 적용
    if text.startswith(('/가족방최고', '!가족방최고')):
        user_msg_id = update.message.message_id
        r_chat_id = str(chat_id)
        today_str = datetime.now(KST).strftime("%Y%m%d")
        
        if not box_event_rooms.get(r_chat_id, False):
            err_msg = await update.message.reply_text("💨 상자 없음!")
            if update.effective_chat.type != "private": asyncio.create_task(delete_messages_delayed(context, chat_id, [user_msg_id, err_msg.message_id], 3.0))
            return
            
        user_record = col_scores.find_one({"chat_id": r_chat_id, "user_id": str(uid), "game": "snake"})
        e_lv = user_record.get("enhancement_level", 0) if user_record else 0
        e_tag = get_e_tag(e_lv)
        bonus_pct = e_lv * 0.01
        d_name = f"<b>{uname}</b>" if e_lv >= 6 else uname
        
        today_box_count = user_record.get("today_box_count", 0) if user_record and user_record.get("last_box_date") == today_str else 0
        if today_box_count >= 5:
            limit_msg = await update.message.reply_text(f"🛑 {e_tag}{d_name}님, 연합상자는 하루 최대 5번까지만 주워 먹을 수 있습니다.")
            if update.effective_chat.type != "private": asyncio.create_task(delete_messages_delayed(context, chat_id, [user_msg_id, limit_msg.message_id], 3.0))
            return
            
        box_event_rooms[r_chat_id] = False
        box_bonus = random.randint(300, 2000)
        actual_bonus = int(box_bonus * (1 + bonus_pct))
        b_gained = actual_bonus - box_bonus
        new_box_count = today_box_count + 1
        
        col_scores.update_one({"chat_id": r_chat_id, "user_id": str(uid), "game": "snake"}, {"$inc": {"score": actual_bonus}, "$set": {"user_name": uname, "last_box_date": today_str, "today_box_count": new_box_count}}, upsert=True)
        b_txt = f" (🌟강화보너스 +{b_gained:,}P)" if b_gained > 0 else ""
        await update.message.reply_text(f"🎉 {e_tag}{d_name}(<code>{uid}</code>) 상자 획득! +{actual_bonus:,}P 지급{b_txt}. ({new_box_count}/5)", parse_mode="HTML")
        return

    if uid in ADMIN_LIST and text.upper().startswith('/BET예약마감'):
        time_digit = re.sub(r'[^0-9]', '', text)
        if len(time_digit) != 12: return await update.message.reply_text("⚠️ 규격 오류! 년월일시분 12자리 숫자로 적어주세요.\n예시: /BET예약마감202606101900")
        try:
            target_dt = datetime.strptime(time_digit, "%Y%m%d%H%M").replace(tzinfo=KST)
            if target_dt <= datetime.now(KST): return await update.message.reply_text("⚠️ 과거 시간은 마감 예약 지정이 불가능합니다.")
            c_room_str = str(chat_id)
            if c_room_str in bet_timer_tasks and not bet_timer_tasks[c_room_str].done(): bet_timer_tasks[c_room_str].cancel()
            bet_timer_tasks[c_room_str] = asyncio.create_task(bet_reservation_worker(context.bot, chat_id, target_dt))
            return await update.message.reply_text(f"⏰ <b>[배팅판 자동 마감 예약 완료]</b>\n\n• <b>마감 설정 시각</b>: {target_dt.strftime('%Y-%m-%d %H:%M')} (KST)", parse_mode="HTML")
        except Exception as e: return await update.message.reply_text(f"❌ 날짜 파싱 오류: {e}")

    if uid in ADMIN_LIST and text.upper().startswith('/BET '):
        match = re.search(r'/[bB][eE][tT]\s+([^-]+)-([^\s]+)\s*(\d*)', text)
        if not match: return await update.message.reply_text("⚠️ /BET A(배당)-B(배당) 판돈")
        cond_a, cond_b, min_p = match.group(1).strip(), match.group(2).strip(), int(match.group(3)) if match.group(3) else 100
        rate_a = float(re.search(r'\(([\d.]+)\)', cond_a).group(1)) if re.search(r'\(([\d.]+)\)', cond_a) else 1.0
        rate_b = float(re.search(r'\(([\d.]+)\)', cond_b).group(1)) if re.search(r'\(([\d.]+)\)', cond_b) else 1.0
        for ob in list(col_user_bets.find({"chat_id": str(chat_id), "amount": {"$exists": True}})): col_scores.update_one({"chat_id": str(chat_id), "user_id": str(ob['user_id']), "game": "snake"}, {"$inc": {"score": ob['amount']}}, upsert=True)
        col_bets.delete_many({"chat_id": str(chat_id)}); col_user_bets.delete_many({"chat_id": str(chat_id)})
        col_bets.insert_one({"chat_id": str(chat_id), "status": "open", "min_p": min_p, "A_name": cond_a, "A_rate": rate_a, "B_name": cond_b, "B_rate": rate_b})
        btns = [[InlineKeyboardButton(f"🅰️ {cond_a}", callback_data="select_team:A"), InlineKeyboardButton(f"🅱️ {cond_b}", callback_data="select_team:B")]]
        await update.message.reply_text(f"🔥 <b>[배팅 오픈]</b>\n{cond_a} vs {cond_b}", reply_markup=InlineKeyboardMarkup(btns), parse_mode="HTML")
        return

    if uid in ADMIN_LIST and text.upper() in ["/BET마감", "/BET마감 "]:
        res = col_bets.update_one({"chat_id": str(chat_id)}, {"$set": {"status": "closed"}}); c_room_str = str(chat_id)
        if c_room_str in bet_timer_tasks: bet_timer_tasks[c_room_str].cancel()
        return await update.message.reply_text("🔒 <b>예측 배팅이 즉시 수동 마감되었습니다.</b>", parse_mode="HTML") if res.modified_count > 0 else await update.message.reply_text("⚠️ 현재 활성화된 배팅판이 존재하지 않습니다.")

    if uid in ADMIN_LIST and text.upper().startswith(('/BET정산 ', '!BET정산 ')):
        ans = text.split()[-1].upper()
        if ans not in ['A', 'B']: return await update.message.reply_text("⚠️ 결과를 A 혹은 B 로 명확히 지정하세요.")
        game_bet = col_bets.find_one({"chat_id": str(chat_id)})
        if not game_bet: return await update.message.reply_text("⚠️ 정산할 예측 배팅판이 존재하지 않습니다.")
        win_rate, win_name = game_bet.get(f"{ans}_rate", 1.0), game_bet.get(f"{ans}_name", "")
        winners = list(col_user_bets.find({"chat_id": str(chat_id), "choice": ans, "amount": {"$exists": True}}))
        report = f"🎉 <b>[예측 배팅 정산 브리핑]</b>\n🎯 적중 조건: {win_name}\n📊 배당률: {win_rate}배\n\n"
        for w in winners:
            w_uid = str(w['user_id'])
            u_rec_w = col_scores.find_one({"chat_id": str(chat_id), "user_id": w_uid, "game": "snake"})
            e_lv = u_rec_w.get("enhancement_level", 0) if u_rec_w else 0
            e_tag = get_e_tag(e_lv)
            bonus_pct = e_lv * 0.01

            base_win = int(w['amount'] * win_rate)
            actual_win = int(base_win * (1 + bonus_pct))
            b_gained = actual_win - base_win
            
            col_scores.update_one({"chat_id": str(chat_id), "user_id": w_uid, "game": "snake"}, {"$inc": {"score": actual_win}}, upsert=True)
            b_txt = f" (+🌟{b_gained:,})" if b_gained > 0 else ""
            
            d_name = f"<b>{w['user_name']}</b>" if e_lv >= 6 else w['user_name']
            report += f"• {e_tag}{d_name}님: +{actual_win:,} P 적중 완료{b_txt}\n"
            
        col_bets.delete_many({"chat_id": str(chat_id)}); col_user_bets.delete_many({"chat_id": str(chat_id)})
        c_room_str = str(chat_id)
        if c_room_str in bet_timer_tasks: bet_timer_tasks[c_room_str].cancel()
        return await update.message.reply_text(report if winners else f"📋 정산 확정 완료!\n해당 조건[{win_name}]에 배팅 적중한 유저가 없습니다.", parse_mode="HTML")

    if uid in ADMIN_LIST and text.upper() in ["/BET적특", "/BET적특 "]:
        game_bet = col_bets.find_one({"chat_id": str(chat_id)})
        if not game_bet: return await update.message.reply_text("⚠️ 취소 처리할 배팅판이 없습니다.")
        all_participants = list(col_user_bets.find({"chat_id": str(chat_id), "amount": {"$exists": True}}))
        refund_report = "⛈ <b>[경기 취소 적중특례 적특 발동]</b>\n참여 유저분들의 베팅 원금이 전액 무결점 롤백 환불 반환되었습니다.\n\n"
        for p in all_participants: col_scores.update_one({"chat_id": str(chat_id), "user_id": str(p['user_id']), "game": "snake"}, {"$inc": {"score": p['amount']}}, upsert=True); refund_report += f"• {p['user_name']}님: {p['amount']:,} P 반환\n"
        col_bets.delete_many({"chat_id": str(chat_id)}); col_user_bets.delete_many({"chat_id": str(chat_id)})
        c_room_str = str(chat_id)
        if c_room_str in bet_timer_tasks: bet_timer_tasks[c_room_str].cancel()
        return await update.message.reply_text(refund_report if all_participants else "📋 적특 완료! 반환할 배팅 내역 청소 완료.", parse_mode="HTML")

    if text.startswith(('/날씨', '!날씨')):
        if not WEATHER_API_KEY: return await update.message.reply_text("⚠️ 날씨 API 키가 설정되지 않았습니다.")
        status_msg = await update.message.reply_text("🛰 <b>한·일 전 구장 예보 데이터 취합 중...</b>", parse_mode="HTML")
        w_ko = {"clear": "☀️맑음", "clouds": "☁️흐림", "rain": "🌧비", "drizzle": "🌦이슬비", "thunderstorm": "⛈폭우", "snow": "❄️눈", "mist": "🌫안개"}
        msg = f"⚾️ <b>한·일 프로야구장 시간별 기상 브리핑 (15시 / 18시)</b>\n🗓 기준일: {datetime.now(KST).strftime('%m월 %d일')}\n\n"
        for league, list_stadiums in STADIUMS.items():
            msg += f"■ <b>{league}</b>\n"
            for s_name, coord in list_stadiums.items():
                try:
                    url = f"http://api.openweathermap.org/data/2.5/forecast?lat={coord['lat']}&lon={coord['lon']}&appid={WEATHER_API_KEY}&units=metric"
                    res = requests.get(url, timeout=8).json()
                    if str(res.get("cod")) != "200": msg += f"• {s_name}: 데이터 유실\n"; continue
                    timeline_forecasts, today_str = datetime.now(KST).strftime("%Y-%m-%d"), []
                    dome_tag = " [돔]" if "돔" in s_name else ""
                    for item in res.get("list", []):
                        dt_kst = datetime.fromtimestamp(item['dt'], tz=timezone.utc).astimezone(KST)
                        if dt_kst.strftime("%Y-%m-%d") == today_str and dt_kst.hour in [15, 18]:
                            sky_ko = w_ko.get(item['weather'][0]['main'].lower(), item['weather'][0]['main'].lower())
                            timeline_forecasts.append(f"{dt_kst.hour}시({sky_ko},{round(item['main']['temp'], 1)}℃)")
                    if timeline_forecasts: msg += f"• <b>{s_name}{dome_tag}</b>\n  └ {', '.join(timeline_forecasts)}\n"
                    else: msg += f"• <b>{s_name}{dome_tag}</b>\n  └ ☀️맑음 기상 안정\n"
                except: msg += f"• {s_name}: 연동 지연\n"
            msg += "\n"
        await status_msg.delete(); await update.message.reply_text(msg, parse_mode="HTML")
        return

    if text.startswith(('/', '!')):
        cmd = re.sub(r"^[ /!]+", "", text.split()[0]).strip()
        room = col_members.find_one({"chat_id": str(chat_id)})
        main_data = col_main.find_one({"id": "bot_main_data"}) or {}
        target = (room.get("local_commands", {}).get(cmd) if room else None) or main_data.get("commands", {}).get(cmd)
        if target: await send_custom_output(context.bot, chat_id, target)

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; data = query.data
    uid, chat_id, uname = query.from_user.id, query.message.chat_id, query.from_user.first_name
    if data.startswith("select_team:"):
        choice = data.split(":")[1]; game_bet = col_bets.find_one({"chat_id": str(chat_id)})
        if not game_bet or game_bet.get("status") == "closed": return await query.answer("⚠️ 마감되었거나 종료된 예측 배팅판입니다.", show_alert=True)
        already_done = col_user_bets.find_one({"chat_id": str(chat_id), "user_id": str(uid), "amount": {"$exists": True}})
        if already_done: return await query.answer("❌ 이미 배팅이 마킹 처리되어 수정할 수 없습니다.", show_alert=True)
        col_user_bets.update_one({"chat_id": str(chat_id), "user_id": str(uid)}, {"$set": {"choice": choice, "user_name": uname}}, upsert=True)
        cond_a, cond_b = game_bet['A_name'], game_bet['B_name']
        btns = [
            [InlineKeyboardButton(f"{'✅ ' if choice == 'A' else ''}{cond_a}", callback_data="select_team:A"), InlineKeyboardButton(f"{'✅ ' if choice == 'B' else ''}{cond_b}", callback_data="select_team:B")],
            [InlineKeyboardButton("💰 1,000 P", callback_data="amt:1000"), InlineKeyboardButton("💰 5,000 P", callback_data="amt:5000"), InlineKeyboardButton("💰 10,000 P", callback_data="amt:10000")],
            [InlineKeyboardButton("💥 보유 전액 [올인]", callback_data="amt:all")]
        ]
        await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(btns)); await query.answer("👉 팀 선택 완료. 판돈 단추를 누르세요!")
    elif data.startswith("amt:"):
        amt_str = data.split(":")[1]; game_bet = col_bets.find_one({"chat_id": str(chat_id)})
        if not game_bet or game_bet.get("status") == "closed": return await query.answer("⚠️ 마감되었습니다.", show_alert=True)
        sess_bet = col_user_bets.find_one({"chat_id": str(chat_id), "user_id": str(uid)})
        if not sess_bet or "choice" not in sess_bet: return await query.answer("☝ 팀 단추를 먼저 눌러주세요.", show_alert=True)
        if "amount" in sess_bet: return await query.answer("❌ 이미 참여 완료된 배팅판입니다.", show_alert=True)
        u_rec = col_scores.find_one({"chat_id": str(chat_id), "user_id": str(uid), "game": "snake"}); c_score = u_rec['score'] if u_rec else 0
        amt = c_score if amt_str == "all" else int(amt_str)
        if amt < game_bet['min_p']: return await query.answer(f"⚠️ 최소 배팅금액은 {game_bet['min_p']}P 입니다.", show_alert=True)
        if c_score < amt: return await query.answer("❌ 잔액이 부족합니다!", show_alert=True)
        col_scores.update_one({"chat_id": str(chat_id), "user_id": str(uid), "game": "snake"}, {"$inc": {"score": -amt}}); col_user_bets.update_one({"chat_id": str(chat_id), "user_id": str(uid)}, {"$set": {"amount": amt}})
        await query.answer(f"🎉 배팅 접수 완료!", show_alert=True); c_name = game_bet['A_name'] if sess_bet['choice'] == 'A' else game_bet['B_name']
        await context.bot.send_message(chat_id=chat_id, text=f"🎯 <b>[예측 배팅 마킹 성공]</b>\n\n• 유저명 : {uname}\n• 마킹 조건 : {c_name}\n• 베팅 판돈 : {amt} P", parse_mode="HTML")
    elif query.from_user.id in ADMIN_LIST and data.startswith("set_room:"):
        r_id = data.split(":")[1]; col_sessions.update_one({"admin_id": query.from_user.id}, {"$set": {"target_chat_id": r_id}}, upsert=True)
        btns = [[InlineKeyboardButton("📋 커맨드 목록", callback_data=f"show_list:{r_id}"), InlineKeyboardButton("⏰ 스케줄 목록", callback_data=f"show_sched:{r_id}")]]
        await query.edit_message_text(f"🎯 활성화됨 ID {r_id}\n이제 사진이나 메시지를 보내 저장하세요.", reply_markup=InlineKeyboardMarkup(btns))
    elif query.from_user.id in ADMIN_LIST and data.startswith("show_list:"):
        r_id = data.split(":")[1]; main_data = col_main.find_one({"id": "bot_main_data"}) or {}; target = main_data.get("commands", {}) if r_id == "common" else (col_members.find_one({"chat_id": r_id}).get("local_commands", {}) if col_members.find_one({"chat_id": r_id}) else {})
        btns = [[InlineKeyboardButton(f"🗑 {k}", callback_data=f"del:{r_id}:{k}")] for k in target.keys()]; btns.append([InlineKeyboardButton("🔙 뒤로", callback_data="back_to_rooms")])
        if btns and btns[0]: await query.edit_message_text("🗑 삭제할 커맨드 선택:", reply_markup=InlineKeyboardMarkup(btns))
    elif query.from_user.id in ADMIN_LIST and data.startswith("show_sched:"):
        r_id = data.split(":")[1]; btns = [[InlineKeyboardButton(f"🗑 {s['name']}", callback_data=f"dsched:{s['_id']}")] for s in list(col_sched.find({"chat_id": r_id}))]; btns.append([InlineKeyboardButton("🔙 뒤로", callback_data="back_to_rooms")])
        if btns and btns[0]: await query.edit_message_text("⏰ 스케줄 목록", reply_markup=InlineKeyboardMarkup(btns))
    elif query.from_user.id in ADMIN_LIST and data.startswith("del:"):
        _, r_id, k = data.split(":", 2); col_main.update_one({"id": "bot_main_data"}, {"$unset": {f"commands.{k}": ""}}) if r_id == "common" else col_members.update_one({"chat_id": r_id}, {"$unset": {f"local_commands.{k}": ""}})
        await query.answer("삭제 완료!"); main_data = col_main.find_one({"id": "bot_main_data"}) or {}; target = main_data.get("commands", {}) if r_id == "common" else (col_members.find_one({"chat_id": r_id}).get("local_commands", {}) if col_members.find_one({"chat_id": r_id}) else {})
        btns = [[InlineKeyboardButton(f"🗑 {key}", callback_data=f"del:{r_id}:{key}")] for key in target.keys()]; btns.append([InlineKeyboardButton("🔙 뒤로", callback_data="back_to_rooms")])
        await query.edit_message_text("🗑 삭제할 커맨드 선택:", reply_markup=InlineKeyboardMarkup(btns))
    elif query.from_user.id in ADMIN_LIST and data.startswith("dsched:"):
        _, s_id = data.split(":", 1); sched_item = col_sched.find_one({"_id": ObjectId(s_id)}); r_id = sched_item['chat_id'] if sched_item else "common"; col_sched.delete_one({"_id": ObjectId(s_id)})
        await query.answer("삭제 완료"); btns = [[InlineKeyboardButton(f"🗑 {s['name']}", callback_data=f"dsched:{s['_id']}")] for s in list(col_sched.find({"chat_id": r_id}))]; btns.append([InlineKeyboardButton("🔙 뒤로", callback_data="back_to_rooms")])
        await query.edit_message_text("⏰ 스케줄 목록", reply_markup=InlineKeyboardMarkup(btns))
    elif data == "back_to_rooms":
        btns = [[InlineKeyboardButton("📁 공용 설정", callback_data="set_room:common")]]
        for r in list(col_members.find()):
            if "room_name" in r: btns.append([InlineKeyboardButton(f"🏠 {r['room_name']}", callback_data=f"set_room:{r['chat_id']}")])
        await query.edit_message_text("📂 관리할 방 선택:", reply_markup=InlineKeyboardMarkup(btns))

flask_app = Flask(__name__)
@flask_app.route('/')
def home(): return "OK", 200
@flask_app.route('/sports/live')
def sports_live():
    return """<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no"><title>뜌리 실시간 스코어센터</title><style>body, html { margin: 0; padding: 0; width: 100%; height: 100%; overflow: hidden; background: #151922; } #container-wrapper { width: 100%; height: 100%; position: relative; overflow: hidden; } iframe { width: 100%; border: none; position: absolute; top: 0; left: 0; transform-origin: top left; }</style></head>
<body><div id="container-wrapper"><iframe id="live-frame" src="https://www.flashscore.co.kr/"></iframe></div><script>function adjustLayout() { const frame = document.getElementById('live-frame'); const wrapper = document.getElementById('container-wrapper'); const windowWidth = window.innerWidth; const isMobileDevice = ('ontouchstart' in window) || (navigator.maxTouchPoints > 0); if (isMobileDevice) { const mobileCut = 58; frame.style.transform = 'none'; frame.style.width = '100%'; frame.style.marginTop = `-${mobileCut}px`; frame.style.height = `calc(100% + ${mobileCut}px)`; } else { const pcCut = 120; const baseWidth = 1200; if (windowWidth < baseWidth) { const scale = windowWidth / baseWidth; frame.style.width = baseWidth + 'px'; frame.style.height = ((wrapper.clientHeight / scale) + pcCut) + 'px'; frame.style.transform = `scale(${scale})`; frame.style.marginTop = `-${pcCut}px`; } else { frame.style.width = '100%'; frame.style.height = `calc(100% + ${pcCut}px)`; frame.style.transform = 'none'; frame.style.marginTop = `-${pcCut}px`; } } } window.addEventListener('load', adjustLayout); window.addEventListener('resize', adjustLayout);</script></body></html>"""

def run_flask(): flask_app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)))

async def post_init(application):
    loop = asyncio.get_event_loop(); loop.create_task(userbot.start()); loop.create_task(custom_scheduler_loop(application))

if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    app = ApplicationBuilder().token(TOKEN).post_init(post_init).build()
    app.add_handler(MessageHandler(filters.ALL, handle_message))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.run_polling()
