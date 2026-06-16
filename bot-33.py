from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, MessageHandler, CommandHandler, CallbackQueryHandler, filters, ContextTypes
import yt_dlp
import requests
import os
import base64
import sqlite3
import re
import glob
import io
import time
import logging
import subprocess
from PIL import Image
from datetime import datetime, timedelta

logging.basicConfig(format="%(asctime)s [%(levelname)s] %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = os.environ["BOT_TOKEN"]
RAPIDAPI_KEY = os.environ["RAPIDAPI_KEY"]
CLIPDROP_KEY = os.environ.get("CLIPDROP_KEY", "")

CAPTION = "🎵 ربات موزیک یاب و دانلود\n @downloader_hamechi"
ADMIN_ID = 6206120591  # @Justt_mmd

user_urls = {}
user_search_results = {}
user_artist_data = {}
user_img_state = {}  # برای وضعیت ادیت/ساخت عکس

# ─── دیتابیس ───────────────────────────────────────────────────────────────
DB = "bot.db"

def db():
    return sqlite3.connect(DB)

def init_db():
    with db() as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            user_id     INTEGER PRIMARY KEY,
            username    TEXT,
            first_name  TEXT,
            joined_at   TEXT,
            is_vip      INTEGER DEFAULT 0,
            vip_until   TEXT,
            is_banned   INTEGER DEFAULT 0,
            downloads   INTEGER DEFAULT 0,
            dl_today    INTEGER DEFAULT 0,
            dl_date     TEXT
        );
        CREATE TABLE IF NOT EXISTS stats (
            id          INTEGER PRIMARY KEY CHECK (id=1),
            total       INTEGER DEFAULT 0,
            instagram   INTEGER DEFAULT 0,
            pinterest   INTEGER DEFAULT 0,
            music       INTEGER DEFAULT 0,
            image_gen   INTEGER DEFAULT 0,
            today_total INTEGER DEFAULT 0,
            today_date  TEXT
        );
        CREATE TABLE IF NOT EXISTS settings (
            key   TEXT PRIMARY KEY,
            value TEXT
        );
        INSERT OR IGNORE INTO stats (id, today_date) VALUES (1, date('now'));
        INSERT OR IGNORE INTO settings VALUES ('channel', '@downloader_hamechi');
        INSERT OR IGNORE INTO settings VALUES ('free_limit', '5');
        INSERT OR IGNORE INTO settings VALUES ('maintenance', '0');
        INSERT OR IGNORE INTO settings VALUES ('caption', '🎵 ربات موزیک یاب و دانلود\n @downloader_hamechi');
        INSERT OR IGNORE INTO settings VALUES ('welcome', 'سلام!\n\nلینک اینستاگرام یا پینترست بفرست، اسم آهنگ بنویس، یا از منوی زیر عکس بساز 🎨');
        INSERT OR IGNORE INTO settings VALUES ('vip_price', '30000');
        INSERT OR IGNORE INTO settings VALUES ('vip_days', '30');
        """)

init_db()

def get_setting(key):
    with db() as con:
        row = con.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row[0] if row else None

def set_setting(key, value):
    with db() as con:
        con.execute("INSERT OR REPLACE INTO settings VALUES (?,?)", (key, value))

def register_user(user):
    with db() as con:
        con.execute("""
            INSERT OR IGNORE INTO users (user_id, username, first_name, joined_at, dl_date)
            VALUES (?,?,?,?,?)
        """, (user.id, user.username, user.first_name, datetime.now().isoformat(), datetime.now().date().isoformat()))
        con.execute("UPDATE users SET username=?, first_name=? WHERE user_id=?",
                    (user.username, user.first_name, user.id))

def is_banned(user_id):
    with db() as con:
        row = con.execute("SELECT is_banned FROM users WHERE user_id=?", (user_id,)).fetchone()
        return bool(row and row[0])

def is_vip(user_id):
    with db() as con:
        row = con.execute("SELECT is_vip, vip_until FROM users WHERE user_id=?", (user_id,)).fetchone()
        if not row or not row[0]:
            return False
        if row[1] and datetime.fromisoformat(row[1]) < datetime.now():
            con.execute("UPDATE users SET is_vip=0, vip_until=NULL WHERE user_id=?", (user_id,))
            return False
        return True

def get_user(user_id):
    with db() as con:
        row = con.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
        if row:
            cols = [d[0] for d in con.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).description]
            return dict(zip(cols, row))
        return None

def count_dl_today(user_id):
    with db() as con:
        row = con.execute("SELECT dl_today, dl_date FROM users WHERE user_id=?", (user_id,)).fetchone()
        if not row:
            return 0
        today = datetime.now().date().isoformat()
        if row[1] != today:
            con.execute("UPDATE users SET dl_today=0, dl_date=? WHERE user_id=?", (today, user_id))
            return 0
        return row[0] or 0

def add_download(user_id, kind):
    today = datetime.now().date().isoformat()
    with db() as con:
        con.execute("""
            UPDATE users SET downloads=downloads+1, dl_today=dl_today+1, dl_date=?
            WHERE user_id=?
        """, (today, user_id))
        con.execute(f"UPDATE stats SET total=total+1, {kind}={kind}+1 WHERE id=1")
        row = con.execute("SELECT today_date FROM stats WHERE id=1").fetchone()
        if row and row[0] != today:
            con.execute("UPDATE stats SET today_total=1, today_date=? WHERE id=1", (today,))
        else:
            con.execute("UPDATE stats SET today_total=today_total+1 WHERE id=1")

def get_stats():
    with db() as con:
        row = con.execute("SELECT * FROM stats WHERE id=1").fetchone()
        cols = [d[0] for d in con.execute("SELECT * FROM stats WHERE id=1").description]
        return dict(zip(cols, row)) if row else {}

def get_all_users():
    with db() as con:
        return con.execute("SELECT user_id FROM users WHERE is_banned=0").fetchall()

def get_vip_users():
    with db() as con:
        return con.execute("SELECT user_id, username, first_name, vip_until FROM users WHERE is_vip=1").fetchall()

def get_banned_users():
    with db() as con:
        return con.execute("SELECT user_id, username, first_name FROM users WHERE is_banned=1").fetchall()

def set_vip(user_id, days):
    until = (datetime.now() + timedelta(days=days)).isoformat()
    with db() as con:
        con.execute("UPDATE users SET is_vip=1, vip_until=? WHERE user_id=?", (until, user_id))

def remove_vip(user_id):
    with db() as con:
        con.execute("UPDATE users SET is_vip=0, vip_until=NULL WHERE user_id=?", (user_id,))

def ban_user(user_id):
    with db() as con:
        con.execute("UPDATE users SET is_banned=1 WHERE user_id=?", (user_id,))

def unban_user(user_id):
    with db() as con:
        con.execute("UPDATE users SET is_banned=0 WHERE user_id=?", (user_id,))

# ─── چک عضویت ──────────────────────────────────────────────────────────────
async def is_member(bot, user_id):
    channel = get_setting("channel")
    try:
        member = await bot.get_chat_member(channel, user_id)
        return member.status in ["member", "administrator", "creator"]
    except:
        return False

async def not_joined_message(update):
    channel = get_setting("channel")
    keyboard = [
        [InlineKeyboardButton("عضویت در کانال", url=f"https://t.me/{channel.lstrip('@')}")],
        [InlineKeyboardButton("عضو شدم ✅", callback_data="check_join")]
    ]
    await update.message.reply_text(
        "*سلام!*\n\n*برای استفاده از ربات، اول باید عضو کانال ما بشی*\n\n*بعد از عضویت روی دکمه عضو شدم بزن*",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def check_limit(update, user_id):
    if is_vip(user_id):
        return True
    free_limit = int(get_setting("free_limit") or 5)
    used = count_dl_today(user_id)
    if used >= free_limit:
        keyboard = [[InlineKeyboardButton("💎 خرید VIP", callback_data="buy_vip")]]
        await update.message.reply_text(
            f"⛔️ سقف دانلود رایگان امروزت تموم شده ({free_limit} تا)\n\n"
            f"💎 با خرید VIP، دانلود نامحدود داشته باش!",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return False
    return True

# ─── /start ────────────────────────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    if get_setting("maintenance") == "1" and user.id != ADMIN_ID:
        await update.message.reply_text("🔧 ربات در حال تعمیر است، لطفاً بعداً مراجعه کنید.")
        return
    if is_banned(user.id):
        await update.message.reply_text("⛔️ شما از ربات مسدود شده‌اید.")
        return
    if not await is_member(context.bot, user.id):
        await not_joined_message(update)
        return
    register_user(user)
    user_img_state.pop(user.id, None)
    welcome = get_setting("welcome")
    keyboard = [
        [InlineKeyboardButton("✨ ساخت عکس با هوش مصنوعی", callback_data="img_generate")],
        [InlineKeyboardButton("🖼 ادیت عکس با هوش مصنوعی", callback_data="img_edit")],
    ]
    await update.message.reply_text(
        welcome,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def check_join_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    if await is_member(context.bot, user.id):
        register_user(user)
        await query.answer("عضویت تایید شد ✅")
        welcome = get_setting("welcome")
        keyboard = [
            [InlineKeyboardButton("✨ ساخت عکس با هوش مصنوعی", callback_data="img_generate")],
            [InlineKeyboardButton("🖼 ادیت عکس با هوش مصنوعی", callback_data="img_edit")],
        ]
        await query.message.reply_text(welcome, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await query.answer("هنوز عضو نشدی!", show_alert=True)

async def buy_vip_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    price = get_setting("vip_price")
    days = get_setting("vip_days")
    await query.message.reply_text(
        f"💎 *پلن VIP*\n\n⏳ مدت: {days} روز\n💰 قیمت: {price} تومان\n\nبرای خرید با ادمین در تماس باش:\n@Justt_mmd",
        parse_mode="Markdown"
    )

# ─── ساخت عکس با Pollinations.ai (رایگان، بدون توکن) ─────────────────────
async def ai_generate_image(prompt):
    try:
        import urllib.parse
        encoded = urllib.parse.quote(prompt)
        url = f"https://image.pollinations.ai/prompt/{encoded}?width=1024&height=1024&nologo=true&enhance=true"
        r = requests.get(url, timeout=120)
        if r.status_code == 200 and r.headers.get("content-type", "").startswith("image"):
            return r.content, None
        return None, f"HTTP {r.status_code}"
    except Exception as e:
        return None, str(e)

# ─── ادیت عکس با Clipdrop API ─────────────────────────────────────────────
async def ai_edit_image(img_bytes, instruction):
    try:
        if not CLIPDROP_KEY:
            return None, "کلید CLIPDROP_KEY تنظیم نشده. از https://clipdrop.co/apis کلید رایگان بگیر و توی Railway اضافه کن."
        pil = Image.open(io.BytesIO(img_bytes)).convert("RGB")
        buf = io.BytesIO()
        pil.save(buf, format="PNG")
        buf.seek(0)
        r = requests.post(
            "https://clipdrop-api.co/image-inpainting/v1",
            files={"image_file": ("image.png", buf, "image/png")},
            data={"prompt": instruction},
            headers={"x-api-key": CLIPDROP_KEY},
            timeout=120,
        )
        if r.status_code == 200:
            return r.content, None
        # اگه inpainting نبود، از reimagine استفاده کن
        buf.seek(0)
        r2 = requests.post(
            "https://clipdrop-api.co/reimagine/v1/reimagine",
            files={"image_file": ("image.png", buf, "image/png")},
            headers={"x-api-key": CLIPDROP_KEY},
            timeout=120,
        )
        if r2.status_code == 200:
            return r2.content, None
        return None, f"HTTP {r2.status_code}: {r2.text[:200]}"
    except Exception as e:
        return None, str(e)

# ─── callback های ساخت/ادیت عکس ──────────────────────────────────────────
async def img_mode_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()

    if query.data == "img_generate":
        user_img_state[user_id] = {"mode": "generate"}
        await query.message.reply_text(
            "✨ *ساخت عکس با هوش مصنوعی*\n\n"
            "توضیح بده چه عکسی بسازم:\n\n"
            "مثال:\n"
            "• `a cat astronaut on the moon`\n"
            "• `sunset over a Persian city, oil painting`\n"
            "• `a dragon in forest, fantasy art, detailed`",
            parse_mode="Markdown"
        )

    elif query.data == "img_edit":
        user_img_state[user_id] = {"mode": "edit", "image": None}
        await query.message.reply_text(
            "🖼 *ادیت عکس با هوش مصنوعی*\n\n"
            "عکسی که می‌خوای ادیت بشه رو بفرست.",
            parse_mode="Markdown"
        )

    elif query.data == "img_re_edit":
        await query.message.reply_text("✏️ توضیح بده چه تغییر دیگه‌ای می‌خوای روی همین عکس:")

    elif query.data == "img_edit_generated":
        state = user_img_state.get(user_id, {})
        generated = state.get("last_generated")
        if generated:
            user_img_state[user_id]["mode"] = "edit"
            user_img_state[user_id]["image"] = generated
            await query.message.reply_text("✅ عکس آماده ادیته!\nتوضیح بده چه تغییری می‌خوای:")
        else:
            await query.message.reply_text("عکسی پیدا نشد، دوباره بساز.")

    elif query.data == "img_back":
        user_img_state.pop(user_id, None)
        keyboard = [
            [InlineKeyboardButton("✨ ساخت عکس با هوش مصنوعی", callback_data="img_generate")],
            [InlineKeyboardButton("🖼 ادیت عکس با هوش مصنوعی", callback_data="img_edit")],
        ]
        await query.message.reply_text("چیکار می‌خوای بکنی؟", reply_markup=InlineKeyboardMarkup(keyboard))

# ─── دریافت عکس از کاربر ──────────────────────────────────────────────────
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    if get_setting("maintenance") == "1" and user.id != ADMIN_ID: return
    if is_banned(user.id): return
    if not await is_member(context.bot, user.id):
        await not_joined_message(update); return

    state = user_img_state.get(user.id, {})
    if state.get("mode") != "edit":
        keyboard = [
            [InlineKeyboardButton("✨ ساخت عکس", callback_data="img_generate")],
            [InlineKeyboardButton("🖼 ادیت این عکس", callback_data="img_edit")],
        ]
        await update.message.reply_text(
            "برای ادیت عکس، از منو گزینه *ادیت عکس* رو انتخاب کن:",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    photo = update.message.photo[-1]
    file = await photo.get_file()
    img_bytes = await file.download_as_bytearray()
    user_img_state[user.id]["image"] = bytes(img_bytes)
    await update.message.reply_text(
        "✅ عکس ذخیره شد!\n\n"
        "حالا توضیح بده چه تغییری می‌خوای:\n\n"
        "مثال: `make it look like winter` یا `change background to beach`",
        parse_mode="Markdown"
    )

# ─── موزیک: شناسایی با Shazam ─────────────────────────────────────────────
def shazam_detect_from_file(input_path, rapidapi_key):
    host = "shazam.p.rapidapi.com"
    headers = {"x-rapidapi-key": rapidapi_key, "x-rapidapi-host": host, "Content-Type": "text/plain"}
    tmp_audio = input_path + ".mp3"
    try:
        result = subprocess.run([
            "ffmpeg", "-y", "-i", input_path, "-ss", "3", "-t", "10",
            "-vn", "-ar", "44100", "-ac", "1", "-b:a", "64k", tmp_audio
        ], capture_output=True, timeout=30)
        if not os.path.exists(tmp_audio) or os.path.getsize(tmp_audio) == 0:
            raise Exception(f"ffmpeg failed: {result.stderr.decode()[:200]}")
        with open(tmp_audio, "rb") as f:
            audio_b64 = base64.b64encode(f.read()).decode()
    finally:
        if os.path.exists(tmp_audio): os.remove(tmp_audio)
    r = requests.post(f"https://{host}/songs/v2/detect", headers=headers, data=audio_b64, timeout=60)
    return r.json()

# ─── موزیک: دانلود و ارسال ────────────────────────────────────────────────
async def download_and_send(update, context, title, artist, msg):
    user_id = update.message.from_user.id
    mp3_path = f"song_{user_id}.mp3"
    ydl_opts = {
        "format": "bestaudio/best", "outtmpl": f"song_{user_id}.%(ext)s",
        "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3"}],
        "quiet": True, "noplaylist": True, "socket_timeout": 30,
    }
    downloaded = False
    for search in [f"ytsearch1:{title} {artist} official audio", f"ytsearch1:{title} {artist}",
                   f"scsearch1:{title} {artist}", f"ytsearch1:{title} audio"]:
        if downloaded: break
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl: ydl.download([search])
            if os.path.exists(mp3_path): downloaded = True
        except: pass
    if not downloaded:
        found = glob.glob(f"song_{user_id}.*")
        if found:
            os.rename(found[0], mp3_path)
            downloaded = True
    if not downloaded:
        await msg.edit_text("❌ آهنگ پیدا نشد، اسم دقیق‌تری بنویس."); return
    caption = get_setting("caption") or CAPTION
    await update.message.reply_audio(audio=open(mp3_path,"rb"), title=title, performer=artist, caption=caption)
    add_download(user_id, "music")
    await msg.delete()
    for f in glob.glob(f"song_{user_id}.*"):
        try: os.remove(f)
        except: pass

# ─── ویس ──────────────────────────────────────────────────────────────────
async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    if get_setting("maintenance") == "1" and user.id != ADMIN_ID: return
    if is_banned(user.id): return
    if not await is_member(context.bot, user.id):
        await not_joined_message(update); return
    if not await check_limit(update, user.id): return
    msg = await update.message.reply_text("دارم آهنگ رو شناسایی میکنم...")
    try:
        voice = await update.message.voice.get_file()
        voice_path = f"voice_{user.id}.ogg"
        await voice.download_to_drive(voice_path)
        resp_json = shazam_detect_from_file(voice_path, RAPIDAPI_KEY)
        track = resp_json.get("track")
        if not track:
            await msg.edit_text("آهنگی شناسایی نشد 😔"); return
        title = track.get("title", "نامشخص")
        artist = track.get("subtitle", "نامشخص")
        await msg.edit_text(f"*{title}*\n*{artist}*\nدارم دانلود میکنم...", parse_mode="Markdown")
        await download_and_send(update, context, title, artist, msg)
    except Exception as e:
        await msg.edit_text(f"خطا: {e}")
    finally:
        if os.path.exists(f"voice_{user.id}.ogg"): os.remove(f"voice_{user.id}.ogg")

# ─── ویدیو فوروارد ────────────────────────────────────────────────────────
async def handle_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    if get_setting("maintenance") == "1" and user.id != ADMIN_ID: return
    if is_banned(user.id): return
    if not await is_member(context.bot, user.id):
        await not_joined_message(update); return
    msg = await update.message.reply_text("دارم آهنگ ویدیو رو شناسایی میکنم...")
    tmp_path = f"fwd_{user.id}.mp4"
    try:
        video = update.message.video or update.message.document
        file = await video.get_file()
        await file.download_to_drive(tmp_path)
        resp_json = shazam_detect_from_file(tmp_path, RAPIDAPI_KEY)
        track = resp_json.get("track")
        if not track:
            await msg.edit_text("آهنگی شناسایی نشد 😔\n\n" + str(resp_json)[:300]); return
        title = track.get("title", "نامشخص")
        artist = track.get("subtitle", "نامشخص")
        await msg.edit_text(f"*{title}*\n*{artist}*\nدارم دانلود میکنم...", parse_mode="Markdown")
        await download_and_send(update, context, title, artist, msg)
    except Exception as e:
        await msg.edit_text(f"خطا: {e}")
    finally:
        if os.path.exists(tmp_path): os.remove(tmp_path)

# ─── callback دانلود آهنگ از لیست ─────────────────────────────────────────
def fuzzy_score(query, title):
    q, t = query.lower(), title.lower()
    score = 0
    if q == t: return 100
    if t.startswith(q) or q.startswith(t): score += 50
    score += len(set(q.split()) & set(t.split())) * 20
    q_chars, t_chars = set(q.replace(" ", "")), set(t.replace(" ", ""))
    score += int(len(q_chars & t_chars) / max(len(q_chars), len(t_chars), 1) * 30)
    return score

def search_songs(query):
    results, seen_titles, top_artist_id, top_artist_name = [], set(), None, None
    try:
        with yt_dlp.YoutubeDL({"quiet": True, "extract_flat": True}) as ydl:
            result = ydl.extract_info(f"scsearch10:{query}", download=False)
            for entry in result.get("entries", []):
                title = entry.get("title", "")
                key = title.lower().strip()
                if key not in seen_titles:
                    seen_titles.add(key)
                    results.append({"title": title, "artist": entry.get("uploader", ""),
                        "duration": entry.get("duration", 0),
                        "url": entry.get("url") or entry.get("webpage_url", ""),
                        "score": fuzzy_score(query, title)})
    except: pass
    try:
        r = requests.get("https://api.deezer.com/search", params={"q": query, "limit": 10}, timeout=8)
        tracks = r.json().get("data", [])
        artist_scores = {}
        for track in tracks:
            a_id = track.get("artist", {}).get("id")
            a_name = track.get("artist", {}).get("name", "")
            if a_id and a_id not in artist_scores:
                artist_scores[a_id] = {"name": a_name, "score": fuzzy_score(query, a_name)}
        if artist_scores:
            best_id = max(artist_scores, key=lambda x: artist_scores[x]["score"])
            top_artist_id, top_artist_name = best_id, artist_scores[best_id]["name"]
        for track in tracks:
            title = track.get("title", "")
            artist = track.get("artist", {}).get("name", "")
            key = f"{title} {artist}".lower().strip()
            if key not in seen_titles:
                seen_titles.add(key)
                results.append({"title": title, "artist": artist, "duration": track.get("duration", 0),
                    "url": None, "score": fuzzy_score(query, f"{title} {artist}")})
    except: pass
    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:10], top_artist_id, top_artist_name

def get_artist_tracks(artist_id):
    try:
        r = requests.get(f"https://api.deezer.com/artist/{artist_id}/top", params={"limit": 50}, timeout=8)
        return [{"title": t.get("title",""), "artist": t.get("artist",{}).get("name",""),
                 "duration": t.get("duration",0), "url": None} for t in r.json().get("data",[])]
    except: return []

async def download_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer("در حال دانلود...")
    index = int(query.data.split("_")[1])
    results = user_search_results.get(user_id, [])
    if not results or index >= len(results):
        await query.message.reply_text("خطا، دوباره سرچ کن."); return
    track = results[index]
    title, artist, url = track.get("title", "نامشخص"), track.get("artist", ""), track.get("url")
    msg = await query.message.reply_text(f"دارم دانلود میکنم...\n{title} - {artist}")
    mp3_path = f"song_{user_id}.mp3"
    ydl_opts = {"format": "bestaudio/best", "outtmpl": f"song_{user_id}.%(ext)s",
                "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3"}],
                "quiet": True, "noplaylist": True}
    downloaded = False
    for s in ([url] if url else []) + [f"ytsearch1:{title} {artist} official audio",
               f"ytsearch1:{title} {artist}", f"scsearch1:{title} {artist}"]:
        if downloaded: break
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl: ydl.download([s])
            if os.path.exists(mp3_path): downloaded = True
        except: pass
    if not downloaded:
        found = glob.glob(f"song_{user_id}.*")
        if found: os.rename(found[0], mp3_path); downloaded = True
    if not downloaded:
        await msg.edit_text("❌ آهنگ پیدا نشد."); return
    caption = get_setting("caption") or CAPTION
    try:
        await query.message.reply_audio(audio=open(mp3_path,"rb"), title=title, performer=artist, caption=caption)
        add_download(user_id, "music")
        await msg.delete()
    except Exception as e:
        await msg.edit_text(f"خطا: {e}")
    finally:
        for f in glob.glob(f"song_{user_id}.*"):
            try: os.remove(f)
            except: pass

async def song_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer("در حال جستجوی آهنگ...")
    msg = await query.message.reply_text("دارم آهنگ رو شناسایی میکنم...")
    try:
        video_path = f"video_{user_id}.mp4"
        if not os.path.exists(video_path):
            await msg.edit_text("فایل ویدیو پیدا نشد، دوباره لینک اینستاگرام رو بفرست."); return
        resp_json = shazam_detect_from_file(video_path, RAPIDAPI_KEY)
        track = resp_json.get("track")
        if not track:
            await msg.edit_text(f"آهنگی شناسایی نشد 😔\n\n🔍 پاسخ API:\n<code>{str(resp_json)[:300]}</code>", parse_mode="HTML"); return
        title = track.get("title", "نامشخص")
        artist = track.get("subtitle", "نامشخص")
        await msg.edit_text(f"✅ {title} - {artist}\nدارم دانلود میکنم...")
        mp3_path = f"song_{user_id}.mp3"
        ydl_opts = {"format": "bestaudio/best", "outtmpl": f"song_{user_id}.%(ext)s",
                    "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3"}],
                    "quiet": True, "noplaylist": True}
        downloaded = False
        for s in [f"ytsearch1:{title} {artist} official audio", f"ytsearch1:{title} {artist}",
                  f"scsearch1:{title} {artist}", f"ytsearch1:{title} audio"]:
            if downloaded: break
            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl: ydl.download([s])
                if os.path.exists(mp3_path): downloaded = True
            except: pass
        if not downloaded:
            found = glob.glob(f"song_{user_id}.*")
            if found: os.rename(found[0], mp3_path); downloaded = True
        if not downloaded:
            await msg.edit_text(f"❌ آهنگ پیدا نشد.\n\n🎵 شناسایی شد: {title} - {artist}"); return
        caption = get_setting("caption") or CAPTION
        await query.message.reply_audio(audio=open(mp3_path,"rb"), title=title, performer=artist, caption=caption)
        add_download(user_id, "music")
        await msg.delete()
    except Exception as e:
        await msg.edit_text(f"خطا: {e}")
    finally:
        for p in [f"video_{user_id}.mp4"] + glob.glob(f"song_{user_id}.*"):
            try: os.remove(p)
            except: pass

async def all_songs_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer("در حال دریافت لیست...")
    artist_data = user_artist_data.get(user_id)
    if not artist_data:
        await query.message.reply_text("خطا، دوباره سرچ کن."); return
    msg = await query.message.reply_text(f"دارم آهنگهای {artist_data['name']} رو میگیرم...")
    tracks = get_artist_tracks(artist_data["id"])
    if not tracks:
        await msg.edit_text("آهنگی پیدا نشد"); return
    user_search_results[user_id] = tracks
    keyboard = [[InlineKeyboardButton(f"{t.get('title','')[:28]} - {t.get('artist','')[:15]}", callback_data=f"dl_{i}")]
                for i, t in enumerate(tracks)]
    await msg.delete()
    await query.message.reply_text(f"*همه آهنگهای {artist_data['name']}:*", parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard))

# ─── handle_link: دریافت متن (لینک یا پرامپت عکس یا سرچ آهنگ) ────────────
async def handle_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    if get_setting("maintenance") == "1" and user.id != ADMIN_ID:
        await update.message.reply_text("🔧 ربات در حال تعمیر است."); return
    if is_banned(user.id):
        await update.message.reply_text("⛔️ شما مسدود شده‌اید."); return
    if not await is_member(context.bot, user.id):
        await not_joined_message(update); return
    if await handle_broadcast(update, context): return

    register_user(user)
    text = update.message.text.strip()

    # ─── ساخت عکس با AI ───────────────────────────────────────
    state = user_img_state.get(user.id, {})

    if state.get("mode") == "generate":
        if not await check_limit(update, user.id): return
        msg = await update.message.reply_text("⏳ دارم عکست رو می‌سازم...\nممکنه ۳۰ تا ۶۰ ثانیه طول بکشه 🙏")
        img_data, err = await ai_generate_image(text)
        if err or not img_data:
            await msg.edit_text(f"❌ خطا: {err or 'نتیجه‌ای نگرفتم'}\n\nدوباره امتحان کن."); return
        try:
            Image.open(io.BytesIO(img_data))
        except:
            await msg.edit_text("❌ خروجی عکس نبود. دوباره امتحان کن."); return
        await msg.delete()
        keyboard = [
            [InlineKeyboardButton("🔄 دوباره بساز", callback_data="img_generate")],
            [InlineKeyboardButton("🖼 ادیت همین عکس", callback_data="img_edit_generated")],
            [InlineKeyboardButton("🏠 منوی اصلی", callback_data="img_back")],
        ]
        user_img_state[user.id]["last_generated"] = img_data
        add_download(user.id, "image_gen")
        await update.message.reply_photo(
            photo=io.BytesIO(img_data),
            caption=f"✨ ساخته شد!\n📝 _{text[:200]}_",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    # ─── ادیت عکس با AI ───────────────────────────────────────
    if state.get("mode") == "edit":
        img_bytes = state.get("image")
        if not img_bytes:
            await update.message.reply_text("📸 اول عکس رو بفرست."); return
        if not await check_limit(update, user.id): return
        msg = await update.message.reply_text("⏳ دارم ادیت می‌کنم...\nممکنه ۳۰ تا ۹۰ ثانیه طول بکشه 🙏")
        img_data, err = await ai_edit_image(img_bytes, text)
        if err or not img_data:
            await msg.edit_text(f"❌ خطا: {err or 'نتیجه‌ای نگرفتم'}\n\nدوباره امتحان کن."); return
        try:
            Image.open(io.BytesIO(img_data))
        except:
            await msg.edit_text("❌ خروجی عکس نبود. دوباره امتحان کن."); return
        await msg.delete()
        keyboard = [
            [InlineKeyboardButton("✏️ ادیت مجدد", callback_data="img_re_edit")],
            [InlineKeyboardButton("📸 عکس جدید", callback_data="img_edit")],
            [InlineKeyboardButton("🏠 منوی اصلی", callback_data="img_back")],
        ]
        user_img_state[user.id]["image"] = img_data
        add_download(user.id, "image_gen")
        await update.message.reply_photo(
            photo=io.BytesIO(img_data),
            caption=f"✅ ادیت شد!\n📝 _{text[:200]}_",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    # ─── اینستاگرام ───────────────────────────────────────────
    if "instagram.com" in text:
        if not await check_limit(update, user.id): return
        if "/stories/" in text:
            msg = await update.message.reply_text("دارم استوری رو دانلود میکنم...")
            try:
                host = "instagram-downloader-download-instagram-stories-videos4.p.rapidapi.com"
                headers = {"x-rapidapi-key": RAPIDAPI_KEY, "x-rapidapi-host": host}
                r = requests.get(f"https://{host}/convert", headers=headers, params={"url": text}, timeout=40)
                data = r.json()
                video_url = None
                if isinstance(data, dict):
                    media = data.get("media", [])
                    if media: video_url = media[0].get("url")
                    if not video_url:
                        video_url = data.get("url") or data.get("video_url") or data.get("media_url") or data.get("download_url")
                elif isinstance(data, list) and data:
                    video_url = data[0].get("url") or data[0].get("video_url")
                if not video_url:
                    await msg.edit_text("استوری پیدا نشد"); return
                video_data = requests.get(video_url, timeout=40).content
                path = f"story_{user.id}.mp4"
                with open(path, "wb") as f: f.write(video_data)
                channel = get_setting("channel")
                keyboard = [[InlineKeyboardButton("کانال ما 📢", url=f"https://t.me/{channel.lstrip('@')}")],
                            [InlineKeyboardButton("دریافت آهنگ 🎵", callback_data="get_song")]]
                user_urls[user.id] = text
                await update.message.reply_video(video=open(path,"rb"), reply_markup=InlineKeyboardMarkup(keyboard))
                add_download(user.id, "instagram")
                await msg.delete()
                if os.path.exists(path): os.remove(path)
            except Exception as e:
                await msg.edit_text(f"خطا: {e}")
        else:
            await update.message.reply_text("در حال دانلود...")
            ydl_opts = {"outtmpl": f"video_{user.id}.mp4", "format": "best[ext=mp4]/best", "noplaylist": True}
            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl: ydl.download([text])
                user_urls[user.id] = text
                channel = get_setting("channel")
                keyboard = [[InlineKeyboardButton("کانال ما 📢", url=f"https://t.me/{channel.lstrip('@')}")],
                            [InlineKeyboardButton("دریافت آهنگ 🎵", callback_data="get_song")]]
                await update.message.reply_video(video=open(f"video_{user.id}.mp4","rb"),
                    reply_markup=InlineKeyboardMarkup(keyboard))
                add_download(user.id, "instagram")
            except Exception as e:
                await update.message.reply_text(f"خطا: {e}")

    # ─── پینترست ──────────────────────────────────────────────
    elif "pinterest.com" in text or "pin.it" in text:
        if not await check_limit(update, user.id): return
        msg = await update.message.reply_text("دارم از پینترست دانلود میکنم...")
        try:
            channel = get_setting("channel")
            keyboard = [[InlineKeyboardButton("کانال ما 📢", url=f"https://t.me/{channel.lstrip('@')}")]]
            sent = False
            try:
                ydl_opts = {"outtmpl": f"pinterest_{user.id}.%(ext)s",
                    "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
                    "merge_output_format": "mp4", "noplaylist": True, "quiet": True}
                with yt_dlp.YoutubeDL(ydl_opts) as ydl: ydl.extract_info(text, download=True)
                matches = glob.glob(f"pinterest_{user.id}.*")
                if matches:
                    file_path = matches[0]
                    ext = file_path.rsplit(".", 1)[-1]
                    if ext in ("mp4", "mov", "webm"):
                        caption = get_setting("caption") or CAPTION
                        await update.message.reply_video(video=open(file_path,"rb"), caption=caption,
                            reply_markup=InlineKeyboardMarkup(keyboard), supports_streaming=True)
                        sent = True
            except: pass
            if not sent:
                headers_scrape = {"User-Agent": "Mozilla/5.0", "Accept-Language": "en-US,en;q=0.9"}
                pin_url = text
                if "pin.it" in text:
                    try:
                        redir = requests.get(text, headers=headers_scrape, timeout=15, allow_redirects=True)
                        pin_url = redir.url
                    except: pass
                try:
                    page = requests.get(pin_url, headers=headers_scrape, timeout=20)
                    patterns = [
                        r'"url":"(https://i\.pinimg\.com/originals/[^"]+)"',
                        r'"url":"(https://i\.pinimg\.com/736x/[^"]+)"',
                        r"(https://i\.pinimg\.com/originals/[^\s\"'\\]+)",
                    ]
                    media_url = None
                    for pat in patterns:
                        match = re.search(pat, page.text)
                        if match:
                            media_url = match.group(1).replace("\\u002F", "/"); break
                    if media_url:
                        dl_content = requests.get(media_url, headers=headers_scrape, timeout=30).content
                        ext_img = media_url.split("?")[0].rsplit(".", 1)[-1] or "jpg"
                        img_path = f"pinterest_{user.id}.{ext_img}"
                        with open(img_path, "wb") as fp: fp.write(dl_content)
                        caption = get_setting("caption") or CAPTION
                        await update.message.reply_photo(photo=open(img_path,"rb"), caption=caption,
                            reply_markup=InlineKeyboardMarkup(keyboard))
                        sent = True
                except: pass
            if sent:
                add_download(user.id, "pinterest")
                await msg.delete()
            else:
                await msg.edit_text("دانلود پینترست ممکن نشد، دوباره امتحان کن.")
        except Exception as e:
            await msg.edit_text(f"خطا در دانلود پینترست: {e}")
        finally:
            for f in glob.glob(f"pinterest_{user.id}.*"): os.remove(f)

    # ─── سرچ آهنگ ─────────────────────────────────────────────
    else:
        if not await check_limit(update, user.id): return
        msg = await update.message.reply_text("دارم سرچ میکنم...")
        try:
            results, artist_id, artist_name = search_songs(text)
            if not results:
                await msg.edit_text("نتیجه‌ای پیدا نشد"); return
            user_search_results[user.id] = results
            if artist_id: user_artist_data[user.id] = {"id": artist_id, "name": artist_name}
            keyboard = [[InlineKeyboardButton(f"{t.get('title','')[:28]} - {t.get('artist','')[:15]}", callback_data=f"dl_{i}")]
                        for i, t in enumerate(results)]
            if artist_id and artist_name:
                keyboard.append([InlineKeyboardButton(f"همه آهنگهای {artist_name}", callback_data="all_songs")])
            await msg.edit_text("*نتایج سرچ:*", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
        except Exception as e:
            await msg.edit_text(f"خطا: {e}")

# ─── پنل ادمین ─────────────────────────────────────────────────────────────
def admin_main_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 آمار کلی", callback_data="adm_stats"),
         InlineKeyboardButton("👥 کاربران", callback_data="adm_users_menu")],
        [InlineKeyboardButton("💎 مدیریت VIP", callback_data="adm_vip_menu"),
         InlineKeyboardButton("🚫 بن‌شده‌ها", callback_data="adm_banned")],
        [InlineKeyboardButton("📢 پیام همگانی", callback_data="adm_broadcast_menu"),
         InlineKeyboardButton("⚙️ تنظیمات", callback_data="adm_settings")],
        [InlineKeyboardButton("🔧 حالت تعمیر", callback_data="adm_maintenance")],
    ])

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id != ADMIN_ID: return
    maintenance = "🟡 روشن" if get_setting("maintenance") == "1" else "🟢 خاموش"
    await update.message.reply_text(f"🔧 *پنل ادمین*\n\nحالت تعمیر: {maintenance}",
        parse_mode="Markdown", reply_markup=admin_main_keyboard())

async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    if user_id != ADMIN_ID: return
    await query.answer()
    data = query.data
    back_btn = [[InlineKeyboardButton("🔙 برگشت", callback_data="adm_back")]]

    if data == "adm_back":
        maintenance = "🟡 روشن" if get_setting("maintenance") == "1" else "🟢 خاموش"
        await query.message.edit_text(f"🔧 *پنل ادمین*\n\nحالت تعمیر: {maintenance}",
            parse_mode="Markdown", reply_markup=admin_main_keyboard())

    elif data == "adm_stats":
        s = get_stats()
        today = s.get("today_total", 0) if s.get("today_date") == datetime.now().date().isoformat() else 0
        with db() as con:
            total_users = con.execute("SELECT COUNT(*) FROM users").fetchone()[0]
            vip_count = con.execute("SELECT COUNT(*) FROM users WHERE is_vip=1").fetchone()[0]
            banned_count = con.execute("SELECT COUNT(*) FROM users WHERE is_banned=1").fetchone()[0]
        text = (f"📊 *آمار ربات*\n\n"
                f"👥 کل کاربران: `{total_users}`\n💎 VIP: `{vip_count}`\n🚫 بن‌شده: `{banned_count}`\n\n"
                f"🔢 کل دانلودها: `{s.get('total',0)}`\n📅 دانلود امروز: `{today}`\n"
                f"📸 اینستاگرام: `{s.get('instagram',0)}`\n📌 پینترست: `{s.get('pinterest',0)}`\n"
                f"🎵 موزیک: `{s.get('music',0)}`\n🎨 عکس AI: `{s.get('image_gen',0)}`")
        await query.message.edit_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(back_btn))

    elif data == "adm_users_menu":
        with db() as con:
            total = con.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        keyboard = [
            [InlineKeyboardButton("🔍 سرچ کاربر", callback_data="adm_search_user")],
            [InlineKeyboardButton("🚫 بن کاربر", callback_data="adm_ban_user"),
             InlineKeyboardButton("✅ آنبن کاربر", callback_data="adm_unban_user")],
            [InlineKeyboardButton("🔙 برگشت", callback_data="adm_back")]
        ]
        await query.message.edit_text(f"👥 *مدیریت کاربران*\n\nکل: `{total}` کاربر",
            parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))

    elif data == "adm_vip_menu":
        vips = get_vip_users()
        keyboard = [
            [InlineKeyboardButton("➕ دادن VIP", callback_data="adm_give_vip"),
             InlineKeyboardButton("➖ گرفتن VIP", callback_data="adm_remove_vip")],
            [InlineKeyboardButton("📋 لیست VIPها", callback_data="adm_vip_list")],
            [InlineKeyboardButton("💰 تنظیم قیمت VIP", callback_data="adm_vip_price")],
            [InlineKeyboardButton("🔙 برگشت", callback_data="adm_back")]
        ]
        await query.message.edit_text(f"💎 *مدیریت VIP*\n\nتعداد VIP فعال: `{len(vips)}`",
            parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))

    elif data == "adm_vip_list":
        vips = get_vip_users()
        if not vips:
            await query.message.edit_text("هیچ کاربر VIP فعالی وجود ندارد.",
                reply_markup=InlineKeyboardMarkup(back_btn)); return
        lines = [f"👤 {fname or ''} (@{uname or uid})\n📅 تا: {until[:10] if until else 'نامحدود'}"
                 for uid, uname, fname, until in vips]
        await query.message.edit_text("💎 *کاربران VIP:*\n\n" + "\n\n".join(lines),
            parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(back_btn))

    elif data == "adm_banned":
        banned = get_banned_users()
        if not banned:
            await query.message.edit_text("هیچ کاربر بن‌شده‌ای وجود ندارد.",
                reply_markup=InlineKeyboardMarkup(back_btn)); return
        lines = [f"🚫 {fname or ''} (@{uname or uid}) — `{uid}`" for uid, uname, fname in banned]
        await query.message.edit_text("🚫 *کاربران بن‌شده:*\n\n" + "\n".join(lines),
            parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(back_btn))

    elif data == "adm_settings":
        channel, free_limit, caption = get_setting("channel"), get_setting("free_limit"), get_setting("caption")
        keyboard = [
            [InlineKeyboardButton("✏️ تغییر کپشن", callback_data="adm_set_caption")],
            [InlineKeyboardButton("📣 تغییر کانال", callback_data="adm_set_channel")],
            [InlineKeyboardButton("🔢 محدودیت رایگان", callback_data="adm_set_limit")],
            [InlineKeyboardButton("👋 پیام خوش‌آمد", callback_data="adm_set_welcome")],
            [InlineKeyboardButton("🔙 برگشت", callback_data="adm_back")]
        ]
        await query.message.edit_text(
            f"⚙️ *تنظیمات*\n\n📣 کانال: `{channel}`\n🔢 سقف رایگان: `{free_limit}` در روز\n✏️ کپشن:\n`{caption}`",
            parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))

    elif data == "adm_maintenance":
        new_val = "0" if get_setting("maintenance") == "1" else "1"
        set_setting("maintenance", new_val)
        status = "🟡 روشن" if new_val == "1" else "🟢 خاموش"
        await query.message.edit_text(f"🔧 *پنل ادمین*\n\nحالت تعمیر: {status}",
            parse_mode="Markdown", reply_markup=admin_main_keyboard())

    elif data in ("adm_give_vip", "adm_remove_vip", "adm_ban_user", "adm_unban_user",
                  "adm_search_user", "adm_set_caption", "adm_set_channel",
                  "adm_set_limit", "adm_set_welcome", "adm_broadcast_menu", "adm_vip_price"):
        prompts = {
            "adm_give_vip": "💎 آیدی عددی کاربر رو بفرست (تعداد روز هم بعدش بنویس مثلاً: `123456 30`)",
            "adm_remove_vip": "💎 آیدی عددی کاربری که میخوای VIP رو ازش بگیری بفرست:",
            "adm_ban_user": "🚫 آیدی عددی کاربری که میخوای بن کنی بفرست:",
            "adm_unban_user": "✅ آیدی عددی کاربری که میخوای آنبن کنی بفرست:",
            "adm_search_user": "🔍 آیدی عددی کاربر رو بفرست:",
            "adm_set_caption": "✏️ متن کپشن جدید رو بفرست:",
            "adm_set_channel": "📣 آیدی کانال جدید رو بفرست (مثلاً @mychannel):",
            "adm_set_limit": "🔢 سقف دانلود رایگان روزانه رو بفرست (عدد):",
            "adm_set_welcome": "👋 متن پیام خوش‌آمدگویی جدید رو بفرست:",
            "adm_broadcast_menu": "📢 پیام همگانی رو بفرست:",
            "adm_vip_price": "💰 قیمت VIP (تومان) و تعداد روز رو بفرست (مثلاً: `50000 30`):",
        }
        context.user_data["admin_action"] = data
        kb = [[InlineKeyboardButton("❌ لغو", callback_data="adm_back")]]
        if data == "adm_broadcast_menu":
            kb = [[InlineKeyboardButton("📢 همه", callback_data="adm_bc_all"),
                   InlineKeyboardButton("💎 فقط VIP", callback_data="adm_bc_vip")],
                  [InlineKeyboardButton("👤 فقط رایگان", callback_data="adm_bc_free")],
                  [InlineKeyboardButton("❌ لغو", callback_data="adm_back")]]
        await query.message.edit_text(prompts[data], parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))

    elif data in ("adm_bc_all", "adm_bc_vip", "adm_bc_free"):
        context.user_data["admin_action"] = data
        await query.message.edit_text("📢 متن پیام رو بفرست:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ لغو", callback_data="adm_back")]]))

async def handle_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if user_id != ADMIN_ID: return False
    action = context.user_data.get("admin_action")
    if not action: return False
    context.user_data.pop("admin_action", None)
    text = update.message.text.strip()
    msg = await update.message.reply_text("⏳ در حال پردازش...")

    if action == "adm_give_vip":
        try:
            parts = text.split()
            uid = int(parts[0])
            days = int(parts[1]) if len(parts) > 1 else int(get_setting("vip_days") or 30)
            set_vip(uid, days)
            try: await context.bot.send_message(uid, f"💎 اکانت شما {days} روز VIP شد!")
            except: pass
            await msg.edit_text(f"✅ کاربر `{uid}` برای {days} روز VIP شد.", parse_mode="Markdown")
        except: await msg.edit_text("❌ فرمت اشتباه. مثال: `123456 30`", parse_mode="Markdown")
    elif action == "adm_remove_vip":
        try:
            uid = int(text); remove_vip(uid)
            try: await context.bot.send_message(uid, "⚠️ اشتراک VIP شما پایان یافت.")
            except: pass
            await msg.edit_text(f"✅ VIP کاربر `{uid}` حذف شد.", parse_mode="Markdown")
        except: await msg.edit_text("❌ آیدی اشتباه.")
    elif action == "adm_ban_user":
        try:
            uid = int(text); ban_user(uid)
            await msg.edit_text(f"🚫 کاربر `{uid}` بن شد.", parse_mode="Markdown")
        except: await msg.edit_text("❌ آیدی اشتباه.")
    elif action == "adm_unban_user":
        try:
            uid = int(text); unban_user(uid)
            await msg.edit_text(f"✅ کاربر `{uid}` آنبن شد.", parse_mode="Markdown")
        except: await msg.edit_text("❌ آیدی اشتباه.")
    elif action == "adm_search_user":
        try:
            uid = int(text); u = get_user(uid)
            if not u:
                await msg.edit_text("کاربر پیدا نشد."); return True
            vip_until = u.get("vip_until","")[:10] if u.get("vip_until") else "-"
            await msg.edit_text(
                f"👤 *اطلاعات کاربر*\n\n🆔 آیدی: `{u['user_id']}`\n👤 نام: {u.get('first_name','') or ''}\n"
                f"📛 یوزرنیم: @{u.get('username','') or '-'}\n📅 عضویت: {str(u.get('joined_at',''))[:10]}\n"
                f"💎 VIP: {'بله تا '+vip_until if u.get('is_vip') else 'خیر'}\n"
                f"🚫 بن: {'بله' if u.get('is_banned') else 'خیر'}\n"
                f"📥 کل دانلود: {u.get('downloads',0)}\n📥 دانلود امروز: {u.get('dl_today',0)}",
                parse_mode="Markdown")
        except: await msg.edit_text("❌ آیدی اشتباه.")
    elif action == "adm_set_caption":
        set_setting("caption", text); await msg.edit_text("✅ کپشن آپدیت شد.")
    elif action == "adm_set_channel":
        set_setting("channel", text); await msg.edit_text(f"✅ کانال به `{text}` تغییر کرد.", parse_mode="Markdown")
    elif action == "adm_set_limit":
        try:
            set_setting("free_limit", str(int(text))); await msg.edit_text(f"✅ سقف رایگان به {text} در روز تغییر کرد.")
        except: await msg.edit_text("❌ عدد وارد کن.")
    elif action == "adm_set_welcome":
        set_setting("welcome", text); await msg.edit_text("✅ پیام خوش‌آمدگویی آپدیت شد.")
    elif action == "adm_vip_price":
        try:
            parts = text.split()
            set_setting("vip_price", parts[0])
            if len(parts) > 1: set_setting("vip_days", parts[1])
            await msg.edit_text(f"✅ قیمت VIP: {parts[0]} تومان / {parts[1] if len(parts)>1 else get_setting('vip_days')} روز")
        except: await msg.edit_text("❌ فرمت اشتباه. مثال: `50000 30`", parse_mode="Markdown")
    elif action in ("adm_bc_all", "adm_bc_vip", "adm_bc_free"):
        if action == "adm_bc_all":
            targets = [row[0] for row in get_all_users()]; label = "همه کاربران"
        elif action == "adm_bc_vip":
            targets = [row[0] for row in get_vip_users()]; label = "کاربران VIP"
        else:
            with db() as con:
                targets = [r[0] for r in con.execute("SELECT user_id FROM users WHERE is_vip=0 AND is_banned=0").fetchall()]
            label = "کاربران رایگان"
        success, fail = 0, 0
        await msg.edit_text(f"📢 در حال ارسال به {len(targets)} نفر ({label})...")
        for uid in targets:
            try:
                await context.bot.send_message(uid, text); success += 1
            except: fail += 1
        await msg.edit_text(f"✅ ارسال شد: {success}\n❌ ناموفق: {fail}")
    return True

# ─── راه‌اندازی ────────────────────────────────────────────────────────────
app = ApplicationBuilder().token(TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("admin", admin_panel))
app.add_handler(CallbackQueryHandler(check_join_callback, pattern="^check_join$"))
app.add_handler(CallbackQueryHandler(buy_vip_callback, pattern="^buy_vip$"))
app.add_handler(CallbackQueryHandler(song_callback, pattern="^get_song$"))
app.add_handler(CallbackQueryHandler(all_songs_callback, pattern="^all_songs$"))
app.add_handler(CallbackQueryHandler(download_callback, pattern="^dl_"))
app.add_handler(CallbackQueryHandler(img_mode_callback, pattern="^img_"))
app.add_handler(CallbackQueryHandler(admin_callback, pattern="^adm_"))
app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
app.add_handler(MessageHandler(filters.VOICE, handle_voice))
app.add_handler(MessageHandler(filters.VIDEO | filters.Document.VIDEO, handle_video))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_link))
app.run_polling()
