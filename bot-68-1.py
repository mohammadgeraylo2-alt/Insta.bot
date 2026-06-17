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
import asyncio
import logging
import subprocess
from PIL import Image
from datetime import datetime, timedelta

logging.basicConfig(format="%(asctime)s [%(levelname)s] %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = os.environ["BOT_TOKEN"]
RAPIDAPI_KEY = os.environ["RAPIDAPI_KEY"]
GEMINI_KEY = os.environ.get("GEMINI_KEY", "")
MODELSLAB_KEY = os.environ.get("MODELSLAB_KEY", "")
HF_TOKEN = os.environ.get("HF_TOKEN", "")
REPLICATE_TOKEN = os.environ.get("REPLICATE_TOKEN", "")
ANTHROPIC_KEY = os.environ.get("ANTHROPIC_KEY", "")

CAPTION = "🎵 ربات موزیک یاب و دانلود\n @downloader_hamechi"
ADMIN_ID = 6206120591  # @Justt_mmd

user_urls = {}
user_search_results = {}
user_artist_data = {}
user_img_state = {}  # برای وضعیت ادیت/ساخت عکس
user_vid_state = {}  # برای وضعیت ساخت ویدیو

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

        CREATE TABLE IF NOT EXISTS groups (
            chat_id         INTEGER PRIMARY KEY,
            title           TEXT,
            added_at        TEXT,
            anti_spam       INTEGER DEFAULT 0,
            anti_link       INTEGER DEFAULT 0,
            anti_forward    INTEGER DEFAULT 0,
            anti_bad_words  INTEGER DEFAULT 0,
            captcha         INTEGER DEFAULT 0,
            warn_limit      INTEGER DEFAULT 3,
            welcome_msg     INTEGER DEFAULT 1,
            goodbye_msg     INTEGER DEFAULT 0,
            auto_download   INTEGER DEFAULT 1,
            lock_group      INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS warns (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id  INTEGER,
            user_id  INTEGER,
            reason   TEXT,
            date     TEXT
        );
        CREATE TABLE IF NOT EXISTS mutes (
            chat_id   INTEGER,
            user_id   INTEGER,
            until     TEXT,
            PRIMARY KEY (chat_id, user_id)
        );
        CREATE TABLE IF NOT EXISTS pending_captcha (
            chat_id   INTEGER,
            user_id   INTEGER,
            answer    INTEGER,
            expires   TEXT,
            PRIMARY KEY (chat_id, user_id)
        );
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
    context.bot_data.get("claude_users", set()).discard(user.id)
    welcome = get_setting("welcome")
    keyboard = [
        [InlineKeyboardButton("✨ ساخت عکس با هوش مصنوعی", callback_data="img_generate")],
        [InlineKeyboardButton("🖼 ادیت عکس با هوش مصنوعی", callback_data="img_edit")],
        [InlineKeyboardButton("🎬 ساخت ویدیو با هوش مصنوعی", callback_data="vid_menu")],
        [InlineKeyboardButton("🤖 چت با هوش مصنوعی", callback_data="claude_chat")],
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
            [InlineKeyboardButton("🎬 ساخت ویدیو با هوش مصنوعی", callback_data="vid_menu")],
            [InlineKeyboardButton("🤖 چت با هوش مصنوعی", callback_data="claude_chat")],
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

# ─── بهبود prompt با Gemini: ترجمه + افزایش کیفیت ───────────────────────
def translate_to_english(text):
    """ترجمه فارسی به انگلیسی با MyMemory API (رایگان، بدون نیاز به کلید)"""
    try:
        r = requests.get(
            "https://api.mymemory.translated.net/get",
            params={"q": text[:500], "langpair": "fa|en"},
            timeout=10,
        )
        if r.status_code == 200:
            data = r.json()
            translated = data.get("responseData", {}).get("translatedText", "")
            # اگه ترجمه موفق بود و متن انگلیسی داشت برگردون
            if translated and translated.lower() != text.lower():
                return translated
    except Exception:
        pass
    return text  # اگه ترجمه نشد، همون متن رو برگردون


QUALITY_SUFFIX = (
    ", RAW photo, shot on Canon EOS R5, 85mm f/1.4 prime lens, "
    "photorealistic, hyperrealistic, ultra detailed, sharp focus, "
    "real skin texture with visible pores, cinematic color grading, "
    "volumetric lighting, depth of field bokeh, 8k resolution, "
    "professional photography, film grain"
)

QUALITY_NEGATIVE = (
    "cartoon, anime, illustration, painting, drawing, artistic, render, "
    "digital art, CGI, blurry, low quality, watermark, text"
)


def enhance_prompt(text):
    # ۱) اول Gemini امتحان کن — بهترین کیفیت
    if GEMINI_KEY:
        try:
            msg = (
                "You are a world-class AI image prompt engineer specializing in ultra-photorealistic human photography. "
                "The user gives an idea possibly in Persian. "
                "1) Translate to English if needed. "
                "2) Expand into a rich PHOTOREALISTIC cinematic prompt. "
                "ALWAYS include: RAW photo, Canon EOS R5, 85mm f/1.4, photorealistic, hyperrealistic, "
                "ultra detailed, sharp focus, real skin texture with visible pores, "
                "cinematic color grading, volumetric lighting, depth of field bokeh, 8k resolution. "
                "For people: specify realistic age, ethnicity, clothing details, natural expression. "
                "NEVER use: cartoon, anime, illustration, painting, drawing, render, CGI. "
                "Return ONLY the final English prompt. Max 200 words. "
                "User idea: " + text
            )
            payload = {
                "contents": [{"parts": [{"text": msg}]}],
                "generationConfig": {"temperature": 0.6}
            }
            r = requests.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_KEY}",
                json=payload, timeout=15,
            )
            if r.status_code == 200:
                parts = r.json().get("candidates", [{}])[0].get("content", {}).get("parts", [])
                if parts:
                    result = parts[0].get("text", "").strip()
                    if result:
                        return result
        except Exception:
            pass

    # ۲) fallback: ترجمه با MyMemory + اضافه کردن کیفیت
    translated = translate_to_english(text)
    return translated + QUALITY_SUFFIX

# ─── ساخت عکس: ModelsLab → Gemini → HuggingFace FLUX → Pollinations ────────
async def modelslab_generate(prompt, negative_prompt=""):
    """ساخت عکس با ModelsLab text2img API"""
    if not MODELSLAB_KEY:
        return None

    NEGATIVE = (
        negative_prompt or
        "blurry, low quality, bad anatomy, bad hands, missing fingers, extra fingers, "
        "fused fingers, too many fingers, mutated hands, deformed, ugly, disfigured, "
        "cartoon, anime, illustration, painting, drawing, 3d render, cgi, watermark, "
        "signature, text, logo, nsfw, out of frame, cropped, worst quality, low res, "
        "grainy, noisy, oversaturated, overexposed, underexposed"
    )

    # مدل‌های اولویت‌بندی شده — realistic-vision-v6 بهترین برای آدم واقعیه
    MODELS = ["realistic-vision-v6", "realistic-vision-v51", "sdxl"]

    for model_id in MODELS:
        try:
            payload = {
                "key": MODELSLAB_KEY,
                "model_id": model_id,
                "prompt": prompt,
                "negative_prompt": NEGATIVE,
                "width": "832",
                "height": "1216",
                "samples": "1",
                "num_inference_steps": "35",
                "guidance_scale": 7,
                "enhance_prompt": "yes",
                "enhance_style": "photographic",
                "seed": None,
                "lora_model": None,
                "lora_strength": None,
                "scheduler": "DPMSolverMultistepScheduler",
                "tomesd": "yes",
                "clip_skip": "2",
                "use_karras_sigmas": "yes",
            }
            r = requests.post(
                "https://modelslab.com/api/v6/images/text2img",
                json=payload, timeout=150,
            )
            if r.status_code != 200:
                logger.warning(f"ModelsLab {model_id} HTTP {r.status_code}: {r.text[:200]}")
                continue
            data = r.json()
            status = data.get("status")
            if status == "success":
                output = data.get("output", [])
                if output:
                    img_r = requests.get(output[0], timeout=60)
                    if img_r.status_code == 200:
                        return img_r.content
            elif status == "processing":
                fetch_key = data.get("id")
                for _ in range(20):
                    await asyncio.sleep(6)
                    if fetch_key:
                        poll = requests.post(
                            "https://modelslab.com/api/v6/images/fetch",
                            json={"key": MODELSLAB_KEY, "request_id": fetch_key}, timeout=30
                        )
                    else:
                        break
                    if poll.headers.get("content-type", "").startswith("image"):
                        return poll.content
                    try:
                        pd = poll.json()
                        if pd.get("status") == "success":
                            out = pd.get("output", [])
                            if out:
                                img_r = requests.get(out[0], timeout=60)
                                if img_r.status_code == 200:
                                    return img_r.content
                    except Exception:
                        pass
            else:
                logger.warning(f"ModelsLab {model_id} status={status} msg={data.get('message','')}")
                continue
        except Exception as e:
            logger.warning(f"ModelsLab {model_id} error: {e}")
            continue
    return None


async def modelslab_edit(img_bytes, instruction, negative_prompt=""):
    """ادیت عکس با ModelsLab img2img API"""
    if not MODELSLAB_KEY:
        return None

    NEGATIVE = (
        negative_prompt or
        "blurry, low quality, bad anatomy, bad hands, missing fingers, extra fingers, "
        "fused fingers, mutated hands, deformed, ugly, disfigured, cartoon, anime, "
        "illustration, watermark, text, logo, nsfw, worst quality, grainy"
    )

    try:
        pil = Image.open(io.BytesIO(img_bytes)).convert("RGB")
        # آپلود عکس به ModelsLab
        buf = io.BytesIO()
        pil.save(buf, format="PNG")
        buf.seek(0)
        upload_r = requests.post(
            "https://modelslab.com/api/v6/images/upload",
            data={"key": MODELSLAB_KEY},
            files={"file": ("image.png", buf, "image/png")},
            timeout=60,
        )
        img_url = None
        if upload_r.status_code == 200:
            up_data = upload_r.json()
            img_url = up_data.get("link") or up_data.get("url")

        # اگه آپلود نشد، base64 استفاده کن
        if not img_url:
            buf2 = io.BytesIO()
            pil.save(buf2, format="PNG")
            img_b64 = base64.b64encode(buf2.getvalue()).decode()
            init_image = f"data:image/png;base64,{img_b64}"
        else:
            init_image = img_url

        payload = {
            "key": MODELSLAB_KEY,
            "model_id": "realistic-vision-v6",
            "prompt": instruction,
            "negative_prompt": NEGATIVE,
            "init_image": init_image,
            "width": "832",
            "height": "1216",
            "samples": "1",
            "num_inference_steps": "35",
            "strength": 0.65,
            "guidance_scale": 7,
            "enhance_prompt": "yes",
            "enhance_style": "photographic",
            "scheduler": "DPMSolverMultistepScheduler",
            "clip_skip": "2",
            "use_karras_sigmas": "yes",
            "seed": None,
        }
        r = requests.post(
            "https://modelslab.com/api/v6/images/img2img",
            json=payload, timeout=150,
        )
        if r.status_code != 200:
            logger.warning(f"ModelsLab img2img HTTP {r.status_code}: {r.text[:200]}")
            return None
        data = r.json()
        status = data.get("status")
        if status == "success":
            output = data.get("output", [])
            if output:
                img_r = requests.get(output[0], timeout=60)
                if img_r.status_code == 200:
                    return img_r.content
        elif status == "processing":
            fetch_key = data.get("id")
            for _ in range(20):
                await asyncio.sleep(6)
                if fetch_key:
                    poll = requests.post(
                        "https://modelslab.com/api/v6/images/fetch",
                        json={"key": MODELSLAB_KEY, "request_id": fetch_key}, timeout=30
                    )
                else:
                    break
                if poll.headers.get("content-type", "").startswith("image"):
                    return poll.content
                try:
                    pd = poll.json()
                    if pd.get("status") == "success":
                        out = pd.get("output", [])
                        if out:
                            img_r = requests.get(out[0], timeout=60)
                            if img_r.status_code == 200:
                                return img_r.content
                except Exception:
                    pass
    except Exception as e:
        logger.warning(f"ModelsLab edit error: {e}")
    return None


async def ai_generate_image(prompt):
    import urllib.parse
    import asyncio
    # بهبود و ترجمه prompt با Gemini
    enhanced = enhance_prompt(prompt)

    # ۱) اول ModelsLab — کیفیت عالی
    if MODELSLAB_KEY:
        result = await modelslab_generate(enhanced)
        if result:
            return result, None

    # ۲) Gemini image
    if GEMINI_KEY:
        try:
            payload = {
                "contents": [{"parts": [{"text": enhanced}]}],
                "generationConfig": {
                    "responseModalities": ["IMAGE", "TEXT"],
                    "temperature": 1,
                }
            }
            r = requests.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-image:generateContent?key={GEMINI_KEY}",
                json=payload, timeout=120,
            )
            if r.status_code == 200:
                data = r.json()
                for part in data.get("candidates", [{}])[0].get("content", {}).get("parts", []):
                    if part.get("inlineData", {}).get("mimeType", "").startswith("image"):
                        return base64.b64decode(part["inlineData"]["data"]), None
        except Exception:
            pass

    # ۳) HuggingFace FLUX.1-dev
    HF_KEY = os.environ.get("HF_KEY", "")
    if HF_KEY:
        try:
            r = requests.post(
                "https://api-inference.huggingface.co/models/black-forest-labs/FLUX.1-dev",
                headers={"Authorization": f"Bearer {HF_KEY}"},
                json={"inputs": enhanced, "parameters": {"width": 1024, "height": 1024}},
                timeout=120,
            )
            if r.status_code == 200 and r.headers.get("content-type", "").startswith("image"):
                return r.content, None
        except Exception:
            pass

    # ۴) Pollinations به عنوان backup
    try:
        encoded = urllib.parse.quote(enhanced)
        url = f"https://image.pollinations.ai/prompt/{encoded}?width=1024&height=1024&nologo=true&enhance=true&model=flux-realism&seed={int(time.time())}"
        r = requests.get(url, timeout=120)
        if r.status_code == 200 and r.headers.get("content-type", "").startswith("image"):
            return r.content, None
        return None, f"همه سرویس‌ها خطا دادن (HTTP {r.status_code})"
    except Exception as e:
        return None, str(e)

# ─── ادیت عکس: ModelsLab (اصلی) → Gemini (اختیاری) ─────────────────────
async def ai_edit_image(img_bytes, instruction):

    # بهبود پرامپت — اگه Gemini خطا داد از متن خام استفاده میشه
    try:
        enhanced_instruction = enhance_prompt(instruction)
    except Exception:
        enhanced_instruction = instruction

    # ۱) ModelsLab img2img — اصلی
    if MODELSLAB_KEY:
        result = await modelslab_edit(img_bytes, enhanced_instruction)
        if result:
            return result, None

    # ۲) Gemini — فقط اگه key داره و ModelsLab نشد
    if GEMINI_KEY:
        try:
            pil = Image.open(io.BytesIO(img_bytes)).convert("RGB")
            buf = io.BytesIO()
            pil.save(buf, format="PNG")
            img_b64 = base64.b64encode(buf.getvalue()).decode()
            payload = {
                "contents": [{
                    "parts": [
                        {"inline_data": {"mime_type": "image/png", "data": img_b64}},
                        {"text": enhanced_instruction}
                    ]
                }],
                "generationConfig": {
                    "responseModalities": ["IMAGE", "TEXT"],
                    "temperature": 1,
                }
            }
            r = requests.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-image:generateContent?key={GEMINI_KEY}",
                json=payload, timeout=120,
            )
            if r.status_code == 200:
                data = r.json()
                for part in data.get("candidates", [{}])[0].get("content", {}).get("parts", []):
                    if part.get("inlineData", {}).get("mimeType", "").startswith("image"):
                        return base64.b64decode(part["inlineData"]["data"]), None
        except Exception:
            pass

    # ۳) Pollinations — رایگان، بدون نیاز به کلید
    try:
        import urllib.parse
        encoded = urllib.parse.quote(f"{enhanced_instruction}, high quality, photorealistic, detailed")
        url = f"https://image.pollinations.ai/prompt/{encoded}?width=1024&height=1024&nologo=true&enhance=true&model=flux-realism&seed={int(time.time())}"
        r = requests.get(url, timeout=120)
        if r.status_code == 200 and r.headers.get("content-type", "").startswith("image"):
            return r.content, None
    except Exception as e:
        logger.warning(f"Pollinations edit fallback error: {e}")

    return None, "سرویس ادیت موقتاً در دسترس نیست. دوباره امتحان کن 🙏"

# ─── ساخت ویدیو با ModelsLab text2video ─────────────────────────────────
async def modelslab_text2video(prompt):
    if not MODELSLAB_KEY:
        return None, "کلید MODELSLAB_KEY تنظیم نشده."
    try:
        payload = {
            "key": MODELSLAB_KEY,
            "model_id": "cogvideox",
            "prompt": prompt,
            "negative_prompt": "blurry, low quality, watermark, text, logo, nsfw, static, no motion",
            "height": "512",
            "width": "512",
            "num_frames": "49",
            "num_inference_steps": "50",
            "guidance_scale": 7,
            "output_type": "mp4",
            "fps": 8,
            "seed": None,
        }
        r = requests.post(
            "https://modelslab.com/api/v6/video/text2video",
            json=payload, timeout=30,
        )
        if r.status_code != 200:
            return None, f"HTTP {r.status_code}"
        data = r.json()
        status = data.get("status")
        if status == "success":
            output = data.get("output", [])
            if output:
                vr = requests.get(output[0], timeout=120)
                if vr.status_code == 200:
                    return vr.content, None
        elif status == "processing":
            fetch_key = data.get("id")
            for _ in range(30):
                await asyncio.sleep(8)
                if not fetch_key:
                    break
                poll = requests.post(
                    "https://modelslab.com/api/v6/video/fetch",
                    json={"key": MODELSLAB_KEY, "request_id": fetch_key}, timeout=30
                )
                try:
                    pd = poll.json()
                    if pd.get("status") == "success":
                        out = pd.get("output", [])
                        if out:
                            vr = requests.get(out[0], timeout=120)
                            if vr.status_code == 200:
                                return vr.content, None
                    elif pd.get("status") == "failed":
                        return None, pd.get("message", "خطای نامشخص")
                except Exception:
                    pass
        msg = data.get("message", "نتیجه‌ای دریافت نشد")
        # اگه کردیت تموم شده بود، None برگردون تا fallback فعال بشه
        if "credit" in msg.lower() or "fund" in msg.lower() or "subscribe" in msg.lower():
            return None, None
        return None, msg
    except Exception as e:
        return None, str(e)


async def modelslab_img2video(img_bytes, prompt=""):
    if not MODELSLAB_KEY:
        return None, "کلید MODELSLAB_KEY تنظیم نشده."
    try:
        # آپلود عکس
        pil = Image.open(io.BytesIO(img_bytes)).convert("RGB")
        pil = pil.resize((512, 512))
        buf = io.BytesIO()
        pil.save(buf, format="PNG")
        buf.seek(0)
        upload_r = requests.post(
            "https://modelslab.com/api/v6/images/upload",
            data={"key": MODELSLAB_KEY},
            files={"file": ("image.png", buf, "image/png")},
            timeout=60,
        )
        img_url = None
        if upload_r.status_code == 200:
            up_data = upload_r.json()
            img_url = up_data.get("link") or up_data.get("url")

        if not img_url:
            buf2 = io.BytesIO()
            pil.save(buf2, format="PNG")
            img_b64 = base64.b64encode(buf2.getvalue()).decode()
            img_url = f"data:image/png;base64,{img_b64}"

        payload = {
            "key": MODELSLAB_KEY,
            "model_id": "stable-video-diffusion",
            "init_image": img_url,
            "prompt": prompt or "smooth cinematic motion, high quality video",
            "negative_prompt": "blurry, static, watermark, text, nsfw",
            "height": "512",
            "width": "512",
            "num_frames": "25",
            "num_inference_steps": "30",
            "guidance_scale": 7.5,
            "fps": 8,
            "output_type": "mp4",
            "seed": None,
        }
        r = requests.post(
            "https://modelslab.com/api/v6/video/img2video",
            json=payload, timeout=30,
        )
        if r.status_code != 200:
            return None, f"HTTP {r.status_code}"
        data = r.json()
        status = data.get("status")
        if status == "success":
            output = data.get("output", [])
            if output:
                vr = requests.get(output[0], timeout=120)
                if vr.status_code == 200:
                    return vr.content, None
        elif status == "processing":
            fetch_key = data.get("id")
            for _ in range(30):
                await asyncio.sleep(8)
                if not fetch_key:
                    break
                poll = requests.post(
                    "https://modelslab.com/api/v6/video/fetch",
                    json={"key": MODELSLAB_KEY, "request_id": fetch_key}, timeout=30
                )
                try:
                    pd = poll.json()
                    if pd.get("status") == "success":
                        out = pd.get("output", [])
                        if out:
                            vr = requests.get(out[0], timeout=120)
                            if vr.status_code == 200:
                                return vr.content, None
                    elif pd.get("status") == "failed":
                        return None, pd.get("message", "خطای نامشخص")
                except Exception:
                    pass
        msg = data.get("message", "نتیجه‌ای دریافت نشد")
        if "credit" in msg.lower() or "fund" in msg.lower() or "subscribe" in msg.lower():
            return None, None
        return None, msg
    except Exception as e:
        return None, str(e)



# ─── ساخت ویدیو با Replicate (fallback) ─────────────────────────────────
async def replicate_text2video(prompt):
    """ساخت ویدیو از پرامپت با Replicate"""
    if not REPLICATE_TOKEN:
        return None, "کلید REPLICATE_TOKEN تنظیم نشده."
    try:
        headers = {
            "Authorization": f"Token {REPLICATE_TOKEN}",
            "Content-Type": "application/json",
        }
        payload = {
            "input": {
                "prompt": prompt,
                "num_inference_steps": 30,
                "guidance_scale": 7.5,
            }
        }
        r = requests.post(
            "https://api.replicate.com/v1/models/minimax/video-01/predictions",
            headers=headers,
            json=payload,
            timeout=30,
        )
        if r.status_code not in (200, 201):
            return None, f"Replicate خطا: {r.status_code} - {r.text[:150]}"
        data = r.json()
        prediction_id = data.get("id")
        if not prediction_id:
            return None, "Replicate: prediction ID دریافت نشد"
        poll_url = f"https://api.replicate.com/v1/predictions/{prediction_id}"
        for _ in range(60):
            await asyncio.sleep(5)
            pr = requests.get(poll_url, headers=headers, timeout=30)
            if pr.status_code != 200:
                continue
            pd = pr.json()
            status = pd.get("status")
            if status == "succeeded":
                output = pd.get("output")
                video_url = output[0] if isinstance(output, list) else output
                if video_url:
                    vr = requests.get(video_url, timeout=120)
                    if vr.status_code == 200:
                        return vr.content, None
            elif status == "failed":
                return None, pd.get("error", "Replicate: خطای نامشخص")
        return None, "Replicate: timeout - ویدیو آماده نشد"
    except Exception as e:
        return None, str(e)


async def replicate_img2video(img_bytes, prompt=""):
    """تبدیل عکس به ویدیو با Replicate - مدل stable-video-diffusion"""
    if not REPLICATE_TOKEN:
        return None, "کلید REPLICATE_TOKEN تنظیم نشده."
    try:
        headers = {
            "Authorization": f"Token {REPLICATE_TOKEN}",
            "Content-Type": "application/json",
        }
        pil = Image.open(io.BytesIO(img_bytes)).convert("RGB")
        pil = pil.resize((1024, 576))
        buf = io.BytesIO()
        pil.save(buf, format="PNG")
        img_b64 = base64.b64encode(buf.getvalue()).decode()
        img_data_url = f"data:image/png;base64,{img_b64}"

        payload = {
            "input": {
                "input_image": img_data_url,
                "frames_per_second": 8,
                "num_frames": 25,
                "motion_bucket_id": 127,
                "cond_aug": 0.02,
            }
        }
        r = requests.post(
            "https://api.replicate.com/v1/models/stability-ai/stable-video-diffusion/predictions",
            headers=headers,
            json=payload,
            timeout=30,
        )
        if r.status_code not in (200, 201):
            return None, f"Replicate خطا: {r.status_code} - {r.text[:150]}"
        data = r.json()
        prediction_id = data.get("id")
        if not prediction_id:
            return None, "Replicate: prediction ID دریافت نشد"
        poll_url = f"https://api.replicate.com/v1/predictions/{prediction_id}"
        for _ in range(60):
            await asyncio.sleep(5)
            pr = requests.get(poll_url, headers=headers, timeout=30)
            if pr.status_code != 200:
                continue
            pd = pr.json()
            status = pd.get("status")
            if status == "succeeded":
                output = pd.get("output")
                video_url = output[0] if isinstance(output, list) else output
                if video_url:
                    vr = requests.get(video_url, timeout=120)
                    if vr.status_code == 200:
                        return vr.content, None
            elif status == "failed":
                return None, pd.get("error", "Replicate: خطای نامشخص")
        return None, "Replicate: timeout - ویدیو آماده نشد"
    except Exception as e:
        return None, str(e)


# alias برای سازگاری با کد قبلی
async def hf_text2video(prompt):
    return await replicate_text2video(prompt)

async def hf_img2video(img_bytes, prompt=""):
    return await replicate_img2video(img_bytes, prompt)



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
        user_vid_state.pop(user_id, None)
        keyboard = [
            [InlineKeyboardButton("✨ ساخت عکس با هوش مصنوعی", callback_data="img_generate")],
            [InlineKeyboardButton("🖼 ادیت عکس با هوش مصنوعی", callback_data="img_edit")],
            [InlineKeyboardButton("🎬 ساخت ویدیو با هوش مصنوعی", callback_data="vid_menu")],
            [InlineKeyboardButton("🤖 چت با هوش مصنوعی", callback_data="claude_chat")],
        ]
        await query.message.reply_text("چیکار می‌خوای بکنی؟", reply_markup=InlineKeyboardMarkup(keyboard))


# ─── callback های ساخت ویدیو ─────────────────────────────────────────────
async def vid_mode_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()

    if query.data == "vid_menu":
        user_img_state.pop(user_id, None)
        user_vid_state.pop(user_id, None)
        keyboard = [
            [InlineKeyboardButton("📝 پرامپت → ویدیو", callback_data="vid_text")],
            [InlineKeyboardButton("🖼 عکس → ویدیو", callback_data="vid_image")],
            [InlineKeyboardButton("🏠 منوی اصلی", callback_data="img_back")],
        ]
        await query.message.reply_text(
            "🎬 *ساخت ویدیو با هوش مصنوعی*\n\nروش ساخت رو انتخاب کن:",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    elif query.data == "vid_text":
        user_vid_state[user_id] = {"mode": "text2video"}
        user_img_state.pop(user_id, None)
        await query.message.reply_text(
            "🎬 *ساخت ویدیو از پرامپت*\n\nتوضیح بده چه ویدیویی بسازم:\n\nمثال:\n• a cat walking in the rain, cinematic\n• sunset over ocean, waves, slow motion\n\n⏳ ساخت ویدیو ۲ تا ۵ دقیقه طول میکشه!",
            parse_mode="Markdown"
        )

    elif query.data == "vid_image":
        user_vid_state[user_id] = {"mode": "img2video", "image": None}
        user_img_state.pop(user_id, None)
        await query.message.reply_text(
            "🖼 *تبدیل عکس به ویدیو*\n\nعکسی که میخوای متحرک بشه رو بفرست.\n\n⏳ ساخت ویدیو ۲ تا ۵ دقیقه طول میکشه!",
            parse_mode="Markdown"
        )

    elif query.data == "vid_again":
        state = user_vid_state.get(user_id, {})
        mode = state.get("mode")
        if mode == "text2video":
            user_vid_state[user_id] = {"mode": "text2video"}
            await query.message.reply_text("📝 پرامپت جدید بنویس:")
        elif mode == "img2video":
            user_vid_state[user_id] = {"mode": "img2video", "image": None}
            await query.message.reply_text("🖼 عکس جدید بفرست:")
        else:
            keyboard = [[InlineKeyboardButton("🎬 ساخت ویدیو", callback_data="vid_menu")]]
            await query.message.reply_text("از منو شروع کن:", reply_markup=InlineKeyboardMarkup(keyboard))


# ─── دریافت عکس از کاربر ──────────────────────────────────────────────────
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    if get_setting("maintenance") == "1" and user.id != ADMIN_ID: return
    if is_banned(user.id): return
    if not await is_member(context.bot, user.id):
        await not_joined_message(update); return

    # چک ویدیو state اول
    vid_state = user_vid_state.get(user.id, {})
    if vid_state.get("mode") == "img2video":
        photo = update.message.photo[-1]
        file = await photo.get_file()
        img_bytes = await file.download_as_bytearray()
        user_vid_state[user.id]["image"] = bytes(img_bytes)
        await update.message.reply_text(
            "✅ عکس ذخیره شد!\n\nحالا یه توضیح کوتاه بنویس چه حرکتی میخوای (اختیاری):\n\nمثال: slow zoom in, cinematic\n\nیا فقط بنویس بساز تا با تنظیمات پیشفرض بسازه.",
            parse_mode="Markdown"
        )
        return

    state = user_img_state.get(user.id, {})
    if state.get("mode") != "edit":
        keyboard = [
            [InlineKeyboardButton("✨ ساخت عکس", callback_data="img_generate")],
            [InlineKeyboardButton("🖼 ادیت این عکس", callback_data="img_edit")],
            [InlineKeyboardButton("🎬 تبدیل به ویدیو", callback_data="vid_image")],
        ]
        await update.message.reply_text(
            "از منو یه گزینه انتخاب کن:",
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
    tmp_audio = input_path + "_shazam.mp3"

    # چند بار با تایم‌های مختلف امتحان کن
    time_offsets = [("5", "15"), ("20", "15"), ("0", "20")]

    for ss, t in time_offsets:
        try:
            result = subprocess.run([
                "ffmpeg", "-y", "-i", input_path,
                "-ss", ss, "-t", t,
                "-vn", "-ar", "44100", "-ac", "2", "-b:a", "128k",
                tmp_audio
            ], capture_output=True, timeout=30)

            if not os.path.exists(tmp_audio) or os.path.getsize(tmp_audio) == 0:
                continue

            with open(tmp_audio, "rb") as f:
                audio_b64 = base64.b64encode(f.read()).decode()

            if os.path.exists(tmp_audio):
                os.remove(tmp_audio)

            r = requests.post(
                f"https://{host}/songs/v2/detect",
                headers=headers, data=audio_b64, timeout=60
            )
            data = r.json()
            if data.get("track"):
                return data
        except Exception as e:
            logger.warning(f"Shazam attempt ss={ss} error: {e}")
        finally:
            if os.path.exists(tmp_audio):
                try: os.remove(tmp_audio)
                except: pass

    return {}

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

    # ─── چت با هوش مصنوعی ─────────────────────────────────────────
    if user.id in context.bot_data.get("claude_users", set()):
        msg = await update.message.reply_text("⏳ دارم فکر میکنم...")
        reply = await ask_claude(user.id, text)
        await msg.edit_text(reply)
        return

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

    # ─── ساخت ویدیو از پرامپت ───────────────────────────────
    vid_state = user_vid_state.get(user.id, {})

    if vid_state.get("mode") == "text2video":
        if not await check_limit(update, user.id): return
        msg = await update.message.reply_text(
            "🎬 دارم ویدیوت رو می‌سازم...\n⏳ ۲ تا ۵ دقیقه طول میکشه، صبور باش 🙏"
        )
        enhanced = enhance_prompt(text)
        vid_data, err = await modelslab_text2video(enhanced)
        # اگه ModelsLab کردیت نداشت یا خطا داد، Replicate امتحان کن
        if (not vid_data) and REPLICATE_TOKEN:
            await msg.edit_text("🔄 سرویس اصلی در دسترس نیست، از سرویس جایگزین استفاده می‌کنم...\n⏳ کمی بیشتر صبر کن 🙏")
            vid_data, err = await replicate_text2video(enhanced)
        if err or not vid_data:
            await msg.edit_text(f"❌ خطا: {err or 'نتیجه‌ای نگرفتم'}\n\nدوباره امتحان کن.")
            return
        await msg.delete()
        keyboard = [
            [InlineKeyboardButton("🔄 دوباره بساز", callback_data="vid_again")],
            [InlineKeyboardButton("🏠 منوی اصلی", callback_data="img_back")],
        ]
        add_download(user.id, "image_gen")
        await update.message.reply_video(
            video=io.BytesIO(vid_data),
            caption=f"🎬 ویدیو ساخته شد!\n📝 _{text[:150]}_",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    if vid_state.get("mode") == "img2video":
        img_bytes = vid_state.get("image")
        if not img_bytes:
            await update.message.reply_text("🖼 اول عکس رو بفرست.")
            return
        if not await check_limit(update, user.id): return
        prompt = "" if text.strip() in ("بساز", "بساز!", "ok", "OK") else text
        msg = await update.message.reply_text(
            "🎬 دارم ویدیوت رو می‌سازم...\n⏳ ۲ تا ۵ دقیقه طول میکشه، صبور باش 🙏"
        )
        vid_data, err = await modelslab_img2video(img_bytes, prompt)
        # اگه ModelsLab کردیت نداشت یا خطا داد، Replicate امتحان کن
        if (not vid_data) and REPLICATE_TOKEN:
            await msg.edit_text("🔄 سرویس اصلی در دسترس نیست، از سرویس جایگزین استفاده می‌کنم...\n⏳ کمی بیشتر صبر کن 🙏")
            vid_data, err = await replicate_img2video(img_bytes, prompt)
        if err or not vid_data:
            await msg.edit_text(f"❌ خطا: {err or 'نتیجه‌ای نگرفتم'}\n\nدوباره امتحان کن.")
            return
        await msg.delete()
        keyboard = [
            [InlineKeyboardButton("🔄 دوباره بساز", callback_data="vid_again")],
            [InlineKeyboardButton("🏠 منوی اصلی", callback_data="img_back")],
        ]
        add_download(user.id, "image_gen")
        await update.message.reply_video(
            video=io.BytesIO(vid_data),
            caption=f"🎬 ویدیو ساخته شد!",
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
            msg = await update.message.reply_text("⬇️ دارم دانلود میکنم...")
            video_path = f"video_{user.id}.mp4"
            ydl_opts = {"outtmpl": video_path, "format": "best[ext=mp4]/best", "noplaylist": True}
            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl: ydl.download([text])
                user_urls[user.id] = text
                channel = get_setting("channel")
                keyboard = [[InlineKeyboardButton("کانال ما 📢", url=f"https://t.me/{channel.lstrip('@')}")]]
                await update.message.reply_video(video=open(video_path, "rb"),
                    reply_markup=InlineKeyboardMarkup(keyboard))
                add_download(user.id, "instagram")
                await msg.edit_text("🎵 دارم آهنگش رو شناسایی میکنم...")
                try:
                    resp_json = shazam_detect_from_file(video_path, RAPIDAPI_KEY)
                    track = resp_json.get("track")
                    if track:
                        title = track.get("title", "نامشخص")
                        artist = track.get("subtitle", "نامشخص")
                        await msg.edit_text(f"✅ آهنگ پیدا شد!\n🎵 *{title}*\n🎤 *{artist}*\n\nدارم دانلود میکنم...", parse_mode="Markdown")
                        await download_and_send(update, context, title, artist, msg)
                    else:
                        await msg.edit_text(
                            "🎵 آهنگی شناسایی نشد 😔\n\n"
                            "اگه اسم آهنگ رو میدونی مستقیم بنویس تا برات پیدا کنم 👇"
                        )
                except Exception as e:
                    logger.warning(f"Shazam error on instagram: {e}")
                    await msg.edit_text(
                        "🎵 آهنگی شناسایی نشد 😔\n\n"
                        "اگه اسم آهنگ رو میدونی مستقیم بنویس تا برات پیدا کنم 👇"
                    )
            except Exception as e:
                await msg.edit_text(f"خطا: {e}")
            finally:
                if os.path.exists(video_path):
                    try: os.remove(video_path)
                    except: pass

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


# ─── سیستم مدیریت گروه ────────────────────────────────────────────────────

BAD_WORDS = ["فحش1", "فحش2", "بدکلام", "کصکش", "کیر", "کون", "جنده", "مادرجنده", "گاییدم", "گاییدن"]
SPAM_TRACKER = {}  # {(chat_id, user_id): [timestamps]}
FLOOD_TRACKER = {}  # {(chat_id, user_id): [timestamps]} -- برای پنل پیشرفته (ضد فلود)

FLOOD_ACTION_LABELS = {
    "delete": "🗑 فقط حذف پیام",
    "mute":   "🔇 میوت کاربر",
    "kick":   "👋 اخراج (کیک)",
    "ban":    "🚫 بن دائم",
}
FLOOD_ACTION_ORDER = ["delete", "mute", "kick", "ban"]

# ─── مهاجرت ستون‌های جدید برای پنل پیشرفته (بدون دست‌زدن به جدول قبلی) ──────
def migrate_group_columns():
    new_cols = {
        "flood_enabled":      "INTEGER DEFAULT 0",
        "flood_limit":        "INTEGER DEFAULT 7",
        "flood_window":       "INTEGER DEFAULT 10",
        "flood_action":       "TEXT DEFAULT 'mute'",
        "flood_mute_minutes": "INTEGER DEFAULT 10",
        "total_messages":     "INTEGER DEFAULT 0",
        "msgs_today":         "INTEGER DEFAULT 0",
        "msgs_today_date":    "TEXT",
        "total_joins":        "INTEGER DEFAULT 0",
        "total_leaves":       "INTEGER DEFAULT 0",
        "total_deleted":      "INTEGER DEFAULT 0",
        "total_warns_issued": "INTEGER DEFAULT 0",
        "total_mutes_issued": "INTEGER DEFAULT 0",
        "total_bans_issued":  "INTEGER DEFAULT 0",
    }
    with db() as con:
        for name, decl in new_cols.items():
            try:
                con.execute(f"ALTER TABLE groups ADD COLUMN {name} {decl}")
            except sqlite3.OperationalError:
                pass  # ستون از قبل وجود دارد

migrate_group_columns()

def bump_group(chat_id, field, amount=1):
    with db() as con:
        con.execute(f"UPDATE groups SET {field} = COALESCE({field},0) + ? WHERE chat_id=?", (amount, chat_id))

def bump_today_messages(chat_id):
    today = datetime.now().date().isoformat()
    with db() as con:
        row = con.execute("SELECT msgs_today_date FROM groups WHERE chat_id=?", (chat_id,)).fetchone()
        if not row:
            return
        if row[0] != today:
            con.execute("UPDATE groups SET msgs_today=1, msgs_today_date=?, total_messages=COALESCE(total_messages,0)+1 WHERE chat_id=?",
                        (today, chat_id))
        else:
            con.execute("UPDATE groups SET msgs_today=COALESCE(msgs_today,0)+1, total_messages=COALESCE(total_messages,0)+1 WHERE chat_id=?",
                        (chat_id,))

async def check_flood(update, context, chat, user, msg, g):
    """ضد فلود / پیام رگباری — اگه فعال باشه و کاربر بیشتر از حد تعیین‌شده پشت‌سرهم پیام بده برخورد میکنه."""
    if not g.get("flood_enabled"):
        return False
    limit = g.get("flood_limit") or 7
    window = g.get("flood_window") or 10
    key = (chat.id, user.id)
    now = time.time()
    FLOOD_TRACKER.setdefault(key, [])
    FLOOD_TRACKER[key] = [t for t in FLOOD_TRACKER[key] if now - t < window]
    FLOOD_TRACKER[key].append(now)
    if len(FLOOD_TRACKER[key]) <= limit:
        return False
    FLOOD_TRACKER[key] = []
    action = g.get("flood_action") or "mute"
    try:
        await msg.delete()
        bump_group(chat.id, "total_deleted")
    except: pass
    try:
        if action == "delete":
            await chat.send_message(f"🌊 {user.first_name} لطفاً پشت‌سرهم پیام نده!")
        elif action == "mute":
            minutes = g.get("flood_mute_minutes") or 10
            mute_user(chat.id, user.id, minutes)
            from telegram import ChatPermissions
            await context.bot.restrict_chat_member(chat.id, user.id,
                permissions=ChatPermissions(can_send_messages=False),
                until_date=datetime.now() + timedelta(minutes=minutes))
            bump_group(chat.id, "total_mutes_issued")
            await chat.send_message(f"🌊 {user.first_name} به‌خاطر پیام رگباری برای {minutes} دقیقه میوت شد.")
        elif action == "kick":
            await context.bot.ban_chat_member(chat.id, user.id)
            await context.bot.unban_chat_member(chat.id, user.id)
            bump_group(chat.id, "total_bans_issued")
            await chat.send_message(f"🌊 {user.first_name} به‌خاطر پیام رگباری از گروه اخراج شد.")
        elif action == "ban":
            await context.bot.ban_chat_member(chat.id, user.id)
            bump_group(chat.id, "total_bans_issued")
            await chat.send_message(f"🌊 {user.first_name} به‌خاطر پیام رگباری بن شد.")
    except Exception as e:
        logger.warning(f"flood action error: {e}")
    return True

def get_group(chat_id):
    with db() as con:
        row = con.execute("SELECT * FROM groups WHERE chat_id=?", (chat_id,)).fetchone()
        if row:
            cols = [d[0] for d in con.execute("SELECT * FROM groups WHERE chat_id=?", (chat_id,)).description]
            return dict(zip(cols, row))
    return None

def register_group(chat_id, title):
    with db() as con:
        con.execute("INSERT OR IGNORE INTO groups (chat_id, title, added_at) VALUES (?,?,?)",
                    (chat_id, title, datetime.now().isoformat()))
        con.execute("UPDATE groups SET title=? WHERE chat_id=?", (title, chat_id))

def set_group_setting(chat_id, key, value):
    with db() as con:
        con.execute(f"UPDATE groups SET {key}=? WHERE chat_id=?", (value, chat_id))

def get_warn_count(chat_id, user_id):
    with db() as con:
        row = con.execute("SELECT COUNT(*) FROM warns WHERE chat_id=? AND user_id=?", (chat_id, user_id)).fetchone()
        return row[0] if row else 0

def add_warn(chat_id, user_id, reason=""):
    with db() as con:
        con.execute("INSERT INTO warns (chat_id, user_id, reason, date) VALUES (?,?,?,?)",
                    (chat_id, user_id, reason, datetime.now().isoformat()))

def reset_warns(chat_id, user_id):
    with db() as con:
        con.execute("DELETE FROM warns WHERE chat_id=? AND user_id=?", (chat_id, user_id))

def is_muted(chat_id, user_id):
    with db() as con:
        row = con.execute("SELECT until FROM mutes WHERE chat_id=? AND user_id=?", (chat_id, user_id)).fetchone()
        if row:
            if datetime.fromisoformat(row[0]) > datetime.now():
                return True
            con.execute("DELETE FROM mutes WHERE chat_id=? AND user_id=?", (chat_id, user_id))
    return False

def mute_user(chat_id, user_id, minutes):
    until = (datetime.now() + timedelta(minutes=minutes)).isoformat()
    with db() as con:
        con.execute("INSERT OR REPLACE INTO mutes (chat_id, user_id, until) VALUES (?,?,?)",
                    (chat_id, user_id, until))

async def is_group_admin(bot, chat_id, user_id):
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        return member.status in ["administrator", "creator"]
    except:
        return False

def group_settings_keyboard(g):
    def btn(label, key):
        val = g.get(key, 0)
        icon = "✅" if val else "❌"
        return InlineKeyboardButton(f"{icon} {label}", callback_data=f"grp_{key}")
    return InlineKeyboardMarkup([
        [btn("ضد لینک", "anti_link"), btn("ضد فوروارد", "anti_forward")],
        [btn("ضد اسپم", "anti_spam"), btn("ضد فحش", "anti_bad_words")],
        [btn("کپچا عضو جدید", "captcha"), btn("خوش‌آمدگویی", "welcome_msg")],
        [btn("پیام خداحافظی", "goodbye_msg"), btn("دانلود خودکار", "auto_download")],
        [btn("لاک گروه", "lock_group")],
        [InlineKeyboardButton(f"⚠️ سقف وارن: {g.get('warn_limit', 3)}", callback_data="grp_warn_limit")],
    ])

async def cmd_grouppanel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    if chat.type not in ("group", "supergroup"):
        await update.message.reply_text("این دستور فقط در گروه کار میکنه."); return
    if not await is_group_admin(context.bot, chat.id, user.id) and user.id != ADMIN_ID:
        await update.message.reply_text("⛔️ فقط ادمین‌ها میتونن از پنل استفاده کنن."); return
    register_group(chat.id, chat.title)
    g = get_group(chat.id)
    await update.message.reply_text(
        f"⚙️ *پنل مدیریت گروه*\n*{chat.title}*",
        parse_mode="Markdown",
        reply_markup=group_settings_keyboard(g)
    )

async def group_panel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    chat = query.message.chat
    await query.answer()
    if not await is_group_admin(context.bot, chat.id, user.id) and user.id != ADMIN_ID:
        await query.answer("⛔️ فقط ادمین‌ها", show_alert=True); return
    key = query.data.replace("grp_", "")
    if key == "warn_limit":
        g = get_group(chat.id)
        cur = g.get("warn_limit", 3)
        new_val = 2 if cur >= 5 else cur + 1
        set_group_setting(chat.id, "warn_limit", new_val)
    else:
        g = get_group(chat.id)
        cur = g.get(key, 0)
        set_group_setting(chat.id, key, 0 if cur else 1)
    g = get_group(chat.id)
    await query.message.edit_reply_markup(reply_markup=group_settings_keyboard(g))

# ─── پنل پیشرفته گروه (جدید — کنار پنل قبلی، بدون حذف چیزی) ────────────────
def pro_main_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🌊 ضد فلود (پیام رگباری)", callback_data="pro_flood")],
        [InlineKeyboardButton("📊 گزارشات و آمار گروه", callback_data="pro_report")],
        [InlineKeyboardButton("◀️ پنل قبلی (تنظیمات پایه)", callback_data="pro_oldpanel")],
        [InlineKeyboardButton("✖️ بستن", callback_data="pro_close")],
    ])

def pro_flood_text(g, chat_title):
    status = "✅ فعال" if g.get("flood_enabled") else "❌ غیرفعال"
    return (
        f"🌊 *تنظیمات ضد فلود (پیام رگباری)*\n*{chat_title}*\n\n"
        f"وضعیت: {status}\n"
        f"اگه کاربری بیشتر از حد تعیین‌شده پشت‌سرهم پیام بده، به‌صورت خودکار باهاش برخورد میشه."
    )

def pro_flood_keyboard(g):
    enabled = g.get("flood_enabled", 0)
    limit = g.get("flood_limit") or 7
    window = g.get("flood_window") or 10
    mute_min = g.get("flood_mute_minutes") or 10
    action = g.get("flood_action") or "mute"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ فعال" if enabled else "❌ غیرفعال", callback_data="pro_fl_toggle")],
        [InlineKeyboardButton("➖", callback_data="pro_fl_limit_dec"),
         InlineKeyboardButton(f"تعداد پیام: {limit}", callback_data="pro_noop"),
         InlineKeyboardButton("➕", callback_data="pro_fl_limit_inc")],
        [InlineKeyboardButton("➖", callback_data="pro_fl_window_dec"),
         InlineKeyboardButton(f"بازه: {window} ثانیه", callback_data="pro_noop"),
         InlineKeyboardButton("➕", callback_data="pro_fl_window_inc")],
        [InlineKeyboardButton(f"نوع برخورد: {FLOOD_ACTION_LABELS.get(action, action)}", callback_data="pro_fl_action")],
        [InlineKeyboardButton("➖", callback_data="pro_fl_mute_dec"),
         InlineKeyboardButton(f"مدت میوت: {mute_min} دقیقه", callback_data="pro_noop"),
         InlineKeyboardButton("➕", callback_data="pro_fl_mute_inc")],
        [InlineKeyboardButton("◀️ بازگشت", callback_data="pro_back")],
    ])

async def pro_report_text(context, chat):
    g = get_group(chat.id) or {}
    try:
        member_count = await context.bot.get_chat_member_count(chat.id)
    except Exception:
        member_count = "-"
    today = datetime.now().date().isoformat()
    msgs_today = g.get("msgs_today", 0) if g.get("msgs_today_date") == today else 0
    with db() as con:
        active_mutes = con.execute(
            "SELECT COUNT(*) FROM mutes WHERE chat_id=? AND until>?",
            (chat.id, datetime.now().isoformat())
        ).fetchone()[0]
    return (
        f"📊 *گزارشات و آمار گروه*\n*{chat.title}*\n\n"
        f"👥 تعداد اعضا: {member_count}\n"
        f"💬 پیام‌های امروز: {msgs_today}\n"
        f"💬 کل پیام‌های ثبت‌شده: {g.get('total_messages', 0)}\n"
        f"➕ کل جوین‌ها: {g.get('total_joins', 0)}\n"
        f"➖ کل لفت‌ها: {g.get('total_leaves', 0)}\n"
        f"🗑 پیام‌های حذف‌شده (ضدفحش/لینک/فلود و...): {g.get('total_deleted', 0)}\n"
        f"⚠️ کل اخطارهای صادرشده: {g.get('total_warns_issued', 0)}\n"
        f"🔇 میوت‌های فعال الان: {active_mutes}\n"
        f"🔇 کل میوت‌های صادرشده: {g.get('total_mutes_issued', 0)}\n"
        f"🚫 کل بن‌های صادرشده: {g.get('total_bans_issued', 0)}"
    )

async def cmd_propanel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    if chat.type not in ("group", "supergroup"):
        await update.message.reply_text("این دستور فقط در گروه کار میکنه."); return
    if not await is_group_admin(context.bot, chat.id, user.id) and user.id != ADMIN_ID:
        await update.message.reply_text("⛔️ فقط ادمین‌ها میتونن از پنل پیشرفته استفاده کنن."); return
    register_group(chat.id, chat.title)
    await update.message.reply_text(
        f"⚡️ *پنل پیشرفته گروه*\n*{chat.title}*\n\nقابلیت‌های حرفه‌ای جدید رو از این منو مدیریت کن 👇",
        parse_mode="Markdown",
        reply_markup=pro_main_keyboard()
    )

async def pro_panel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    chat = query.message.chat
    if not await is_group_admin(context.bot, chat.id, user.id) and user.id != ADMIN_ID:
        await query.answer("⛔️ فقط ادمین‌ها", show_alert=True); return
    data = query.data
    register_group(chat.id, chat.title)

    if data == "pro_noop":
        await query.answer(); return

    if data == "pro_close":
        await query.answer()
        try: await query.message.delete()
        except: pass
        return

    if data == "pro_back":
        await query.answer()
        await query.message.edit_text(
            f"⚡️ *پنل پیشرفته گروه*\n*{chat.title}*\n\nقابلیت‌های حرفه‌ای جدید رو از این منو مدیریت کن 👇",
            parse_mode="Markdown", reply_markup=pro_main_keyboard())
        return

    if data == "pro_oldpanel":
        await query.answer()
        g = get_group(chat.id) or {}
        await query.message.edit_text(
            f"⚙️ *پنل مدیریت گروه*\n*{chat.title}*",
            parse_mode="Markdown", reply_markup=group_settings_keyboard(g))
        return

    if data == "pro_flood":
        await query.answer()
        g = get_group(chat.id) or {}
        await query.message.edit_text(pro_flood_text(g, chat.title), parse_mode="Markdown", reply_markup=pro_flood_keyboard(g))
        return

    if data == "pro_report":
        await query.answer()
        text = await pro_report_text(context, chat)
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 بروزرسانی", callback_data="pro_report")],
            [InlineKeyboardButton("◀️ بازگشت", callback_data="pro_back")],
        ])
        try:
            await query.message.edit_text(text, parse_mode="Markdown", reply_markup=keyboard)
        except Exception:
            pass
        return

    g = get_group(chat.id) or {}
    if data == "pro_fl_toggle":
        set_group_setting(chat.id, "flood_enabled", 0 if g.get("flood_enabled") else 1)
    elif data == "pro_fl_limit_inc":
        set_group_setting(chat.id, "flood_limit", min((g.get("flood_limit") or 7) + 1, 50))
    elif data == "pro_fl_limit_dec":
        set_group_setting(chat.id, "flood_limit", max((g.get("flood_limit") or 7) - 1, 2))
    elif data == "pro_fl_window_inc":
        set_group_setting(chat.id, "flood_window", min((g.get("flood_window") or 10) + 5, 120))
    elif data == "pro_fl_window_dec":
        set_group_setting(chat.id, "flood_window", max((g.get("flood_window") or 10) - 5, 5))
    elif data == "pro_fl_mute_inc":
        set_group_setting(chat.id, "flood_mute_minutes", min((g.get("flood_mute_minutes") or 10) + 5, 1440))
    elif data == "pro_fl_mute_dec":
        set_group_setting(chat.id, "flood_mute_minutes", max((g.get("flood_mute_minutes") or 10) - 5, 1))
    elif data == "pro_fl_action":
        cur = g.get("flood_action") or "mute"
        idx = FLOOD_ACTION_ORDER.index(cur) if cur in FLOOD_ACTION_ORDER else 1
        set_group_setting(chat.id, "flood_action", FLOOD_ACTION_ORDER[(idx + 1) % len(FLOOD_ACTION_ORDER)])
    else:
        await query.answer(); return

    await query.answer()
    g = get_group(chat.id) or {}
    await query.message.edit_text(pro_flood_text(g, chat.title), parse_mode="Markdown", reply_markup=pro_flood_keyboard(g))

async def cmd_warn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    if chat.type not in ("group", "supergroup"): return
    if not await is_group_admin(context.bot, chat.id, user.id) and user.id != ADMIN_ID:
        await update.message.reply_text("⛔️ فقط ادمین‌ها"); return
    if not update.message.reply_to_message:
        await update.message.reply_text("روی پیام کاربر ریپلای کن و /warn بزن."); return
    target = update.message.reply_to_message.from_user
    reason = " ".join(context.args) if context.args else "بدون دلیل"
    g = get_group(chat.id) or {}
    warn_limit = g.get("warn_limit", 3)
    add_warn(chat.id, target.id, reason)
    bump_group(chat.id, "total_warns_issued")
    count = get_warn_count(chat.id, target.id)
    if count >= warn_limit:
        try:
            await context.bot.ban_chat_member(chat.id, target.id)
            reset_warns(chat.id, target.id)
            bump_group(chat.id, "total_bans_issued")
            await update.message.reply_text(f"🚫 {target.first_name} بعد از {count} اخطار بن شد!")
        except Exception as e:
            await update.message.reply_text(f"خطا در بن: {e}")
    else:
        await update.message.reply_text(
            f"⚠️ *اخطار {count}/{warn_limit}* به {target.first_name}\nدلیل: {reason}",
            parse_mode="Markdown"
        )

async def cmd_mute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    if chat.type not in ("group", "supergroup"): return
    if not await is_group_admin(context.bot, chat.id, user.id) and user.id != ADMIN_ID:
        await update.message.reply_text("⛔️ فقط ادمین‌ها"); return
    if not update.message.reply_to_message:
        await update.message.reply_text("روی پیام کاربر ریپلای کن و /mute [دقیقه] بزن."); return
    target = update.message.reply_to_message.from_user
    minutes = int(context.args[0]) if context.args and context.args[0].isdigit() else 60
    mute_user(chat.id, target.id, minutes)
    try:
        until = datetime.now() + timedelta(minutes=minutes)
        from telegram import ChatPermissions
        await context.bot.restrict_chat_member(chat.id, target.id,
            permissions=ChatPermissions(can_send_messages=False),
            until_date=until)
        bump_group(chat.id, "total_mutes_issued")
        await update.message.reply_text(f"🔇 {target.first_name} برای {minutes} دقیقه میوت شد.")
    except Exception as e:
        await update.message.reply_text(f"خطا: {e}")

async def cmd_unmute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    if chat.type not in ("group", "supergroup"): return
    if not await is_group_admin(context.bot, chat.id, user.id) and user.id != ADMIN_ID:
        await update.message.reply_text("⛔️ فقط ادمین‌ها"); return
    if not update.message.reply_to_message:
        await update.message.reply_text("روی پیام کاربر ریپلای کن."); return
    target = update.message.reply_to_message.from_user
    from telegram import ChatPermissions
    try:
        await context.bot.restrict_chat_member(chat.id, target.id,
            permissions=ChatPermissions(can_send_messages=True, can_send_media_messages=True,
                can_send_other_messages=True, can_add_web_page_previews=True))
        with db() as con:
            con.execute("DELETE FROM mutes WHERE chat_id=? AND user_id=?", (chat.id, target.id))
        await update.message.reply_text(f"🔊 {target.first_name} آنمیوت شد.")
    except Exception as e:
        await update.message.reply_text(f"خطا: {e}")

async def cmd_ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    if chat.type not in ("group", "supergroup"): return
    if not await is_group_admin(context.bot, chat.id, user.id) and user.id != ADMIN_ID:
        await update.message.reply_text("⛔️ فقط ادمین‌ها"); return
    if not update.message.reply_to_message:
        await update.message.reply_text("روی پیام کاربر ریپلای کن."); return
    target = update.message.reply_to_message.from_user
    try:
        await context.bot.ban_chat_member(chat.id, target.id)
        bump_group(chat.id, "total_bans_issued")
        await update.message.reply_text(f"🚫 {target.first_name} بن شد.")
    except Exception as e:
        await update.message.reply_text(f"خطا: {e}")

async def cmd_unban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    if chat.type not in ("group", "supergroup"): return
    if not await is_group_admin(context.bot, chat.id, user.id) and user.id != ADMIN_ID:
        await update.message.reply_text("⛔️ فقط ادمین‌ها"); return
    if not update.message.reply_to_message:
        await update.message.reply_text("روی پیام کاربر ریپلای کن."); return
    target = update.message.reply_to_message.from_user
    try:
        await context.bot.unban_chat_member(chat.id, target.id)
        await update.message.reply_text(f"✅ {target.first_name} آنبن شد.")
    except Exception as e:
        await update.message.reply_text(f"خطا: {e}")

async def cmd_resetwarns(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    if chat.type not in ("group", "supergroup"): return
    if not await is_group_admin(context.bot, chat.id, user.id) and user.id != ADMIN_ID:
        await update.message.reply_text("⛔️ فقط ادمین‌ها"); return
    if not update.message.reply_to_message:
        await update.message.reply_text("روی پیام کاربر ریپلای کن."); return
    target = update.message.reply_to_message.from_user
    reset_warns(chat.id, target.id)
    await update.message.reply_text(f"✅ اخطارهای {target.first_name} پاک شد.")

async def cmd_warns(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if chat.type not in ("group", "supergroup"): return
    if not update.message.reply_to_message:
        await update.message.reply_text("روی پیام کاربر ریپلای کن."); return
    target = update.message.reply_to_message.from_user
    g = get_group(chat.id) or {}
    count = get_warn_count(chat.id, target.id)
    await update.message.reply_text(f"⚠️ {target.first_name}: {count}/{g.get('warn_limit', 3)} اخطار")

async def handle_new_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    register_group(chat.id, chat.title)
    g = get_group(chat.id)
    if not g: return
    for member in update.message.new_chat_members:
        if member.is_bot: continue
        bump_group(chat.id, "total_joins")
        if g.get("captcha"):
            import random
            a, b = random.randint(1, 10), random.randint(1, 10)
            answer = a + b
            expires = (datetime.now() + timedelta(minutes=2)).isoformat()
            with db() as con:
                con.execute("INSERT OR REPLACE INTO pending_captcha VALUES (?,?,?,?)",
                            (chat.id, member.id, answer, expires))
            from telegram import ChatPermissions
            try:
                await context.bot.restrict_chat_member(chat.id, member.id,
                    permissions=ChatPermissions(can_send_messages=False))
            except: pass
            keyboard = [[InlineKeyboardButton(str(a+b), callback_data=f"cap_{chat.id}_{member.id}_{answer}"),
                         InlineKeyboardButton(str(a+b+1), callback_data=f"cap_{chat.id}_{member.id}_wrong"),
                         InlineKeyboardButton(str(a+b-1), callback_data=f"cap_{chat.id}_{member.id}_wrong")]]
            await update.message.reply_text(
                f"👋 {member.first_name} عزیز!\nبرای ورود به گروه جواب بده: {a} + {b} = ?\n⏰ ۲ دقیقه وقت داری",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        elif g.get("welcome_msg"):
            await update.message.reply_text(
                f"👋 خوش اومدی {member.first_name}!\nبه گروه *{chat.title}* خوش اومدی 🎉",
                parse_mode="Markdown"
            )

async def handle_left_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    g = get_group(chat.id)
    member = update.message.left_chat_member
    if member and not member.is_bot:
        bump_group(chat.id, "total_leaves")
    if not g or not g.get("goodbye_msg"): return
    if member and not member.is_bot:
        await update.message.reply_text(f"👋 {member.first_name} از گروه رفت.")

async def captcha_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    parts = query.data.split("_")
    chat_id, user_id = int(parts[1]), int(parts[2])
    if query.from_user.id != user_id:
        await query.answer("این کپچا برای تو نیست!", show_alert=True); return
    if parts[3] == "wrong":
        await query.answer("❌ اشتباه! از گروه اخراج شدی.", show_alert=True)
        try: await context.bot.ban_chat_member(chat_id, user_id)
        except: pass
        try: await query.message.delete()
        except: pass
        return
    answer = int(parts[3])
    with db() as con:
        row = con.execute("SELECT answer, expires FROM pending_captcha WHERE chat_id=? AND user_id=?",
                          (chat_id, user_id)).fetchone()
    if not row:
        await query.answer("کپچا منقضی شده.", show_alert=True); return
    if datetime.fromisoformat(row[1]) < datetime.now():
        await query.answer("⏰ وقت تموم شد!", show_alert=True)
        try: await context.bot.ban_chat_member(chat_id, user_id)
        except: pass
        return
    from telegram import ChatPermissions
    await context.bot.restrict_chat_member(chat_id, user_id,
        permissions=ChatPermissions(can_send_messages=True, can_send_media_messages=True,
            can_send_other_messages=True, can_add_web_page_previews=True))
    with db() as con:
        con.execute("DELETE FROM pending_captcha WHERE chat_id=? AND user_id=?", (chat_id, user_id))
    await query.answer("✅ درسته! خوش اومدی!", show_alert=True)
    g = get_group(chat_id)
    if g and g.get("welcome_msg"):
        chat = await context.bot.get_chat(chat_id)
        await query.message.edit_text(
            f"✅ {query.from_user.first_name} تأیید شد و به گروه خوش اومد! 🎉"
        )
    else:
        try: await query.message.delete()
        except: pass

async def handle_group_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    msg = update.message
    if not msg or not user: return
    if chat.type not in ("group", "supergroup"): return

    register_group(chat.id, chat.title)
    g = get_group(chat.id)
    if not g: return

    bump_today_messages(chat.id)  # ─── آمار پیام برای پنل پیشرفته ───

    is_admin = await is_group_admin(context.bot, chat.id, user.id)
    if is_admin or user.id == ADMIN_ID: pass
    else:
        # ─── ضد فلود (پیام رگباری) — پنل پیشرفته ───────────────
        if await check_flood(update, context, chat, user, msg, g):
            return

        # ─── لاک گروه ─────────────────────────────────────────
        if g.get("lock_group"):
            try: await msg.delete()
            except: pass
            bump_group(chat.id, "total_deleted")
            return

        # ─── ضد اسپم ──────────────────────────────────────────
        if g.get("anti_spam"):
            key = (chat.id, user.id)
            now = time.time()
            SPAM_TRACKER.setdefault(key, [])
            SPAM_TRACKER[key] = [t for t in SPAM_TRACKER[key] if now - t < 5]
            SPAM_TRACKER[key].append(now)
            if len(SPAM_TRACKER[key]) >= 5:
                try: await msg.delete()
                except: pass
                bump_group(chat.id, "total_deleted")
                mute_user(chat.id, user.id, 5)
                from telegram import ChatPermissions
                try:
                    await context.bot.restrict_chat_member(chat.id, user.id,
                        permissions=ChatPermissions(can_send_messages=False),
                        until_date=datetime.now() + timedelta(minutes=5))
                    bump_group(chat.id, "total_mutes_issued")
                    await chat.send_message(f"🚫 {user.first_name} به خاطر اسپم ۵ دقیقه میوت شد.")
                except: pass
                return

        # ─── ضد لینک ──────────────────────────────────────────
        if g.get("anti_link") and msg.text:
            dl_domains = ["instagram.com", "pinterest.com", "pin.it", "tiktok.com", "teamtalk"]
            is_dl = any(x in msg.text for x in dl_domains)
            if not is_dl:
                url_pattern = re.compile(r'(https?://|www\.|t\.me/|@\w{5,})', re.IGNORECASE)
                if url_pattern.search(msg.text):
                    try: await msg.delete()
                    except: pass
                    bump_group(chat.id, "total_deleted")
                    await chat.send_message(f"🔗 {user.first_name} لینک ارسال نکن!")
                    return

        # ─── ضد فوروارد ───────────────────────────────────────
        if g.get("anti_forward") and (msg.forward_from or msg.forward_from_chat or msg.forward_date or msg.forward_origin):
            dl_domains = ["instagram.com", "pinterest.com", "pin.it", "tiktok.com", "teamtalk"]
            is_dl = msg.text and any(x in msg.text for x in dl_domains)
            if not is_dl:
                try: await msg.delete()
                except: pass
                bump_group(chat.id, "total_deleted")
                try: await chat.send_message(f"↩️ {user.first_name} فوروارد ممنوعه!")
                except: pass
                return

        # ─── ضد فحش ───────────────────────────────────────────
        if g.get("anti_bad_words") and msg.text:
            text_lower = msg.text.lower()
            if any(w in text_lower for w in BAD_WORDS):
                try: await msg.delete()
                except: pass
                bump_group(chat.id, "total_deleted")
                add_warn(chat.id, user.id, "فحش")
                bump_group(chat.id, "total_warns_issued")
                count = get_warn_count(chat.id, user.id)
                warn_limit = g.get("warn_limit", 3)
                if count >= warn_limit:
                    try:
                        await context.bot.ban_chat_member(chat.id, user.id)
                        reset_warns(chat.id, user.id)
                        bump_group(chat.id, "total_bans_issued")
                        await chat.send_message(f"🚫 {user.first_name} به خاطر فحش‌دادن بن شد!")
                    except: pass
                else:
                    await chat.send_message(f"⚠️ {user.first_name} فحش ممنوع! اخطار {count}/{warn_limit}")
                return

    # ─── دانلود خودکار لینک ───────────────────────────────────
    if msg.text and g.get("auto_download"):
        text = msg.text.strip()
        is_dl_link = any(x in text for x in ["instagram.com", "pinterest.com", "pin.it", "tiktok.com", "teamtalk"])
        if is_dl_link:
            status_msg = await msg.reply_text("⬇️ دارم دانلود میکنم...")
            try:
                video_path = f"grp_{chat.id}_{user.id}.mp4"
                ydl_opts = {"outtmpl": video_path, "format": "best[ext=mp4]/best", "noplaylist": True, "quiet": True}
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.download([text])
                if os.path.exists(video_path):
                    await msg.reply_video(video=open(video_path, "rb"))
                    await status_msg.delete()
                    # شناسایی آهنگ
                    try:
                        await msg.reply_text("🎵 دارم آهنگش رو شناسایی میکنم...")
                        resp = shazam_detect_from_file(video_path, RAPIDAPI_KEY)
                        track = resp.get("track")
                        if track:
                            title = track.get("title", "نامشخص")
                            artist = track.get("subtitle", "نامشخص")
                            song_msg = await msg.reply_text(f"✅ *{title}* - *{artist}*\nدارم دانلود میکنم...", parse_mode="Markdown")
                            mp3_path = f"grp_song_{chat.id}_{user.id}.mp3"
                            ydl_opts2 = {"format": "bestaudio/best", "outtmpl": mp3_path.replace(".mp3", ".%(ext)s"),
                                         "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3"}],
                                         "quiet": True, "noplaylist": True}
                            for s in [f"ytsearch1:{title} {artist} official audio", f"ytsearch1:{title} {artist}"]:
                                try:
                                    with yt_dlp.YoutubeDL(ydl_opts2) as ydl: ydl.download([s])
                                    if os.path.exists(mp3_path): break
                                except: pass
                            if os.path.exists(mp3_path):
                                caption = get_setting("caption") or CAPTION
                                await msg.reply_audio(audio=open(mp3_path, "rb"), title=title, performer=artist, caption=caption)
                                await song_msg.delete()
                                os.remove(mp3_path)
                            else:
                                await song_msg.edit_text(f"✅ آهنگ: *{title}* - *{artist}*\nبرای دانلود اسمش رو بفرست", parse_mode="Markdown")
                        else:
                            await msg.reply_text("آهنگی شناسایی نشد 😔")
                    except Exception as e:
                        logger.warning(f"Group shazam error: {e}")
                else:
                    await status_msg.edit_text("❌ دانلود ممکن نشد.")
            except Exception as e:
                await status_msg.edit_text(f"❌ خطا: {e}")
            finally:
                if os.path.exists(video_path):
                    try: os.remove(video_path)
                    except: pass
            return  # لینک دانلودی بود، کار تمومه

    # ─── چت با ربات در گروه ───────────────────────────────────
    if msg.text:
        text = msg.text.strip()
        bot_name = "ربات"
        try:
            bot_info = await context.bot.get_me()
            bot_username = bot_info.username
        except:
            bot_username = ""

        should_reply = False
        question = text

        # اگه "ربات" یا @username در پیام بود
        if bot_name in text or (bot_username and f"@{bot_username}".lower() in text.lower()):
            should_reply = True
            question = text.replace(bot_name, "").replace(f"@{bot_username}", "").strip()
            if not question:
                question = text

        # اگه روی پیام ربات ریپلای زده شده
        if (msg.reply_to_message and msg.reply_to_message.from_user and
                msg.reply_to_message.from_user.is_bot and
                bot_username and msg.reply_to_message.from_user.username == bot_username):
            should_reply = True
            question = text

        if should_reply and question:
            typing_msg = await msg.reply_text("💭 دارم فکر میکنم...")
            reply = await ask_claude(user.id, question)
            try:
                await typing_msg.edit_text(reply)
            except:
                await msg.reply_text(reply)
user_chat_history = {}  # تاریخچه مکالمه هر کاربر

async def ask_claude(user_id: int, user_message: str) -> str:
    groq_key = os.environ.get("GROQ_KEY", "")
    if not groq_key:
        return "❌ کلید GROQ_KEY تنظیم نشده. لطفاً با ادمین تماس بگیر."
    history = user_chat_history.get(user_id, [])
    history.append({"role": "user", "content": user_message})
    history = history[-20:]
    try:
        payload = {
            "model": "llama-3.3-70b-versatile",
            "messages": [
                {"role": "system", "content": "تو یه دستیار هوشمند فارسی‌زبان هستی. کوتاه، مفید و دوستانه جواب بده. اگه سوال فنی یا انگلیسی بود، به فارسی توضیح بده."},
                *history
            ],
            "max_tokens": 1024,
            "temperature": 0.7
        }
        r = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {groq_key}", "Content-Type": "application/json"},
            json=payload, timeout=30
        )
        if r.status_code == 400:
            # تاریخچه رو پاک کن و دوباره امتحان کن
            user_chat_history.pop(user_id, None)
            payload["messages"] = [
                {"role": "system", "content": "تو یه دستیار هوشمند فارسی‌زبان هستی. کوتاه، مفید و دوستانه جواب بده. اگه سوال فنی یا انگلیسی بود، به فارسی توضیح بده."},
                {"role": "user", "content": user_message}
            ]
            r = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {groq_key}", "Content-Type": "application/json"},
                json=payload, timeout=30
            )
        if r.status_code == 429:
            return "❌ سقف رایگان Groq پر شده. کمی بعد دوباره امتحان کن."
        if r.status_code != 200:
            return f"❌ خطا از Groq: {r.status_code}"
        data = r.json()
        reply = data["choices"][0]["message"]["content"]
        # حذف تگ‌های فکر داخلی DeepSeek
        import re
        reply = re.sub(r'<think>.*?</think>', '', reply, flags=re.DOTALL).strip()
        history.append({"role": "assistant", "content": reply})
        user_chat_history[user_id] = history
        return reply
    except Exception as e:
        logger.error(f"Groq chat error: {e}")
        return f"❌ خطا در اتصال به هوش مصنوعی: {e}"

async def cmd_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    if get_setting("maintenance") == "1" and user.id != ADMIN_ID:
        await update.message.reply_text("🔧 ربات در حال تعمیر است."); return
    if is_banned(user.id): return
    if not await is_member(context.bot, user.id):
        await not_joined_message(update); return
    register_user(user)
    user_img_state.pop(user.id, None)
    user_vid_state.pop(user.id, None)
    if context.args:
        text = " ".join(context.args)
        msg = await update.message.reply_text("⏳ دارم فکر میکنم...")
        reply = await ask_claude(user.id, text)
        await msg.edit_text(reply)
    else:
        context.bot_data.setdefault("claude_users", set()).add(user.id)
        keyboard = [[InlineKeyboardButton("❌ خروج از حالت چت", callback_data="claude_exit")]]
        await update.message.reply_text(
            "🤖 *چت با هوش مصنوعی*\n\nالان در حالت چت هستی. هر چیزی بنویس جواب میده 🤖!\n\nبرای خروج از حالت چت روی دکمه زیر بزن یا /start بفرست.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

async def cmd_clearchat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_chat_history.pop(update.message.from_user.id, None)
    context.bot_data.get("claude_users", set()).discard(update.message.from_user.id)
    await update.message.reply_text("🗑 تاریخچه مکالمه با Claude پاک شد.")

async def claude_exit_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.bot_data.get("claude_users", set()).discard(query.from_user.id)
    keyboard = [
        [InlineKeyboardButton("✨ ساخت عکس با هوش مصنوعی", callback_data="img_generate")],
        [InlineKeyboardButton("🖼 ادیت عکس با هوش مصنوعی", callback_data="img_edit")],
        [InlineKeyboardButton("🎬 ساخت ویدیو با هوش مصنوعی", callback_data="vid_menu")],
        [InlineKeyboardButton("🤖 چت با هوش مصنوعی", callback_data="claude_chat")],
    ]
    await query.message.reply_text("✅ از حالت چت خارج شدی.", reply_markup=InlineKeyboardMarkup(keyboard))

async def claude_chat_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    await query.answer()
    user_img_state.pop(user.id, None)
    user_vid_state.pop(user.id, None)
    context.bot_data.setdefault("claude_users", set()).add(user.id)
    keyboard = [[InlineKeyboardButton("❌ خروج از حالت چت", callback_data="claude_exit")]]
    await query.message.reply_text(
        "🤖 *چت با هوش مصنوعی*\n\nالان در حالت چت هستی. هر چیزی بنویس جواب میده 🤖!\n\nبرای خروج از حالت چت روی دکمه زیر بزن یا /start بفرست.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

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

# ─── دستورات slash ──────────────────────────────────────────────────────────
async def cmd_image(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    if is_banned(user.id): return
    if not await is_member(context.bot, user.id): await not_joined_message(update); return
    register_user(user)
    user_img_state[user.id] = {"mode": "generate"}
    await update.message.reply_text(
        "✨ *ساخت عکس با هوش مصنوعی*\n\nتوضیح بده چه عکسی بسازم (فارسی یا انگلیسی):\n\nمثال:\n• یک زن در حال دویدن در جنگل\n• a dragon flying over a city at night",
        parse_mode="Markdown"
    )

async def cmd_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    if is_banned(user.id): return
    if not await is_member(context.bot, user.id): await not_joined_message(update); return
    register_user(user)
    user_img_state[user.id] = {"mode": "edit", "image": None}
    await update.message.reply_text("🖼 *ادیت عکس*\n\nعکسی که می‌خوای ادیت بشه رو بفرست.", parse_mode="Markdown")

async def cmd_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    if is_banned(user.id): return
    if not await is_member(context.bot, user.id): await not_joined_message(update); return
    register_user(user)
    user_img_state.pop(user.id, None)
    user_vid_state.pop(user.id, None)
    keyboard = [
        [InlineKeyboardButton("📝 پرامپت → ویدیو", callback_data="vid_text")],
        [InlineKeyboardButton("🖼 عکس → ویدیو", callback_data="vid_image")],
        [InlineKeyboardButton("🏠 منوی اصلی", callback_data="img_back")],
    ]
    await update.message.reply_text(
        "🎬 *ساخت ویدیو با هوش مصنوعی*\n\nروش ساخت رو انتخاب کن:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def cmd_music(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    if is_banned(user.id): return
    if not await is_member(context.bot, user.id): await not_joined_message(update); return
    register_user(user)
    user_img_state.pop(user.id, None)
    await update.message.reply_text("🎵 *جستجوی آهنگ*\n\nاسم آهنگ یا خواننده رو بنویس:", parse_mode="Markdown")

async def cmd_vip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    price = get_setting("vip_price"); days = get_setting("vip_days")
    await update.message.reply_text(
        f"💎 *پلن VIP*\n\n⏳ مدت: {days} روز\n💰 قیمت: {price} تومان\n\nبرای خرید با ادمین در تماس باش:\n@Justt_mmd",
        parse_mode="Markdown"
    )

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 *راهنمای ربات*\n\n"
        "/start — شروع و منوی اصلی\n"
        "/image — ساخت عکس با هوش مصنوعی ✨\n"
        "/edit — ادیت عکس با هوش مصنوعی 🖼\n"
        "/video — ساخت ویدیو با هوش مصنوعی 🎬\n"
        "/music — جستجو و دانلود آهنگ 🎵\n"
        "/chat — چت با هوش مصنوعی 🤖\n"
        "/clearchat — پاک کردن تاریخچه چت 🗑\n"
        "/vip — اطلاعات اشتراک VIP 💎\n"
        "/help — راهنما 📖\n\n"
        "*روش‌های استفاده:*\n"
        "• لینک اینستاگرام یا پینترست بفرست\n"
        "• اسم آهنگ بنویس\n"
        "• ویس یا ویدیو بفرست تا آهنگش رو پیدا کنم\n"
        "• عکس بفرست تا ادیتش کنم یا به ویدیو تبدیل بشه\n"
        "• با /chat یا دکمه منو با Claude چت کن",
        parse_mode="Markdown"
    )

# ─── راه‌اندازی ────────────────────────────────────────────────────────────
async def post_init(application):
    await application.bot.set_my_commands([
        ("start",  "شروع و منوی اصلی"),
        ("image",  "ساخت عکس با هوش مصنوعی ✨"),
        ("edit",   "ادیت عکس با هوش مصنوعی 🖼"),
        ("video",  "ساخت ویدیو با هوش مصنوعی 🎬"),
        ("music",  "جستجو و دانلود آهنگ 🎵"),
        ("chat",    "چت با هوش مصنوعی Claude 🤖"),
        ("clearchat", "پاک کردن تاریخچه چت 🗑"),
        ("vip",    "اطلاعات اشتراک VIP 💎"),
        ("help",   "راهنمای ربات 📖"),
    ])

app = ApplicationBuilder().token(TOKEN).post_init(post_init).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("admin", admin_panel))
app.add_handler(CommandHandler("image", cmd_image))
app.add_handler(CommandHandler("edit", cmd_edit))
app.add_handler(CommandHandler("video", cmd_video))
app.add_handler(CommandHandler("music", cmd_music))
app.add_handler(CommandHandler("chat", cmd_chat))
app.add_handler(CommandHandler("clearchat", cmd_clearchat))
app.add_handler(CommandHandler("vip", cmd_vip))
app.add_handler(CommandHandler("help", cmd_help))
app.add_handler(CallbackQueryHandler(claude_exit_callback, pattern="^claude_exit$"))
app.add_handler(CallbackQueryHandler(claude_chat_callback, pattern="^claude_chat$"))
app.add_handler(CallbackQueryHandler(check_join_callback, pattern="^check_join$"))
app.add_handler(CallbackQueryHandler(buy_vip_callback, pattern="^buy_vip$"))
app.add_handler(CallbackQueryHandler(song_callback, pattern="^get_song$"))
app.add_handler(CallbackQueryHandler(all_songs_callback, pattern="^all_songs$"))
app.add_handler(CallbackQueryHandler(download_callback, pattern="^dl_"))
app.add_handler(CallbackQueryHandler(img_mode_callback, pattern="^img_"))
app.add_handler(CallbackQueryHandler(vid_mode_callback, pattern="^vid_"))
app.add_handler(CallbackQueryHandler(admin_callback, pattern="^adm_"))
app.add_handler(CommandHandler("grouppanel", cmd_grouppanel))
app.add_handler(CommandHandler("propanel", cmd_propanel))
app.add_handler(CommandHandler("warn", cmd_warn))
app.add_handler(CommandHandler("mute", cmd_mute))
app.add_handler(CommandHandler("unmute", cmd_unmute))
app.add_handler(CommandHandler("ban", cmd_ban))
app.add_handler(CommandHandler("unban", cmd_unban))
app.add_handler(CommandHandler("warns", cmd_warns))
app.add_handler(CommandHandler("resetwarns", cmd_resetwarns))
app.add_handler(CallbackQueryHandler(group_panel_callback, pattern="^grp_"))
app.add_handler(CallbackQueryHandler(pro_panel_callback, pattern="^pro_"))
app.add_handler(CallbackQueryHandler(captcha_callback, pattern="^cap_"))
app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, handle_new_member))
app.add_handler(MessageHandler(filters.StatusUpdate.LEFT_CHAT_MEMBER, handle_left_member))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.GROUPS, handle_group_message))
app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
app.add_handler(MessageHandler(filters.VOICE, handle_voice))
app.add_handler(MessageHandler(filters.VIDEO | filters.Document.VIDEO, handle_video))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_link))
app.run_polling()
