from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, MessageHandler, CommandHandler, CallbackQueryHandler, filters, ContextTypes
import yt_dlp
import requests
import os
import json

TOKEN = os.environ["BOT_TOKEN"]
RAPIDAPI_KEY = os.environ["RAPIDAPI_KEY"]
CHANNEL = "@downloader_hamechi"
user_urls = {}
user_search_results = {}

async def is_member(bot, user_id):
    try:
        member = await bot.get_chat_member(CHANNEL, user_id)
        return member.status in ["member", "administrator", "creator"]
    except:
        return False

async def not_joined_message(update):
    keyboard = [
        [InlineKeyboardButton("عضویت در کانال", url="https://t.me/downloader_hamechi")],
        [InlineKeyboardButton("عضو شدم", callback_data="check_join")]
    ]
    await update.message.reply_text(
        "*👋 سلام!*\n\n"
        "*برای استفاده از ربات، اول باید عضو کانال ما بشی 🙏*\n\n"
        "*📢 بعد از عضویت روی دکمه «عضو شدم» بزن*",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def check_join_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    if await is_member(context.bot, user_id):
        await query.answer("عضویت تایید شد")
        await query.message.reply_text("سلام! لینک اینستاگرام بفرست یا از /search استفاده کن")
    else:
        await query.answer("هنوز عضو نشدی", show_alert=True)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if not await is_member(context.bot, user_id):
        await not_joined_message(update)
        return
    await update.message.reply_text(
    "*سلام! 👋*\n\n"
    "*لینک اینستاگرام بفرست* برای دانلود ویدیو\n"
    "*اسم آهنگ بنویس* برای سرچ و دانلود\n"
    "*ویس بفرست* برای شناسایی آهنگ",
    parse_mode="Markdown"
    ),

def search_soundcloud(query):
    ydl_opts = {
        "quiet": True,
        "extract_flat": True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        result = ydl.extract_info(f"scsearch5:{query}", download=False)
        if not result:
            return []
        return result.get("entries", [])

async def search_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if not await is_member(context.bot, user_id):
        await not_joined_message(update)
        return

    query = " ".join(context.args)
    if not query:
        await update.message.reply_text("*مثال: /search Eminem Lose Yourself*", parse_mode="Markdown")
        return

    msg = await update.message.reply_text("🔍 دارم سرچ میکنم...")

    try:
        results = search_soundcloud(query)
        if not results:
            await msg.edit_text("نتیجه‌ای پیدا نشد 😔")
            return

        user_search_results[user_id] = results

        keyboard = []
        for i, track in enumerate(results[:5]):
            title = track.get("title", "نامشخص")[:40]
            keyboard.append([InlineKeyboardButton(f"🎵 {title}", callback_data=f"dl_{i}")])

        await msg.edit_text(
            "*نتایج سرچ:*",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    except Exception as e:
        await msg.edit_text(f"❌ خطا: {e}")

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if not await is_member(context.bot, user_id):
        await not_joined_message(update)
        return

    msg = await update.message.reply_text("🎤 دارم آهنگ رو شناسایی میکنم...")

    try:
        voice = await update.message.voice.get_file()
        voice_path = f"voice_{user_id}.ogg"
        await voice.download_to_drive(voice_path)

        with open(voice_path, "rb") as f:
            import base64
            audio_b64 = base64.b64encode(f.read()).decode()

        host = "shazam.p.rapidapi.com"
        headers = {
            "x-rapidapi-key": RAPIDAPI_KEY,
            "x-rapidapi-host": host,
            "Content-Type": "text/plain"
        }
        r = requests.post(
            f"https://{host}/songs/v2/detect",
            headers=headers,
            data=audio_b64
        )
        data = r.json()
        track = data.get("track")

        if not track:
            await msg.edit_text("آهنگی شناسایی نشد 😔")
            return

        title = track.get("title", "نامشخص")
        artist = track.get("subtitle", "نامشخص")

        await msg.edit_text(f"🎵 *{title}*\n👤 *{artist}*\n⬇️ دارم دانلود میکنم...", parse_mode="Markdown")

        await download_and_send(update, context, title, artist, msg)

    except Exception as e:
        await msg.edit_text(f"❌ خطا: {e}")
    finally:
        if os.path.exists(f"voice_{user_id}.ogg"):
            os.remove(f"voice_{user_id}.ogg")

async def download_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer("در حال دانلود...")

    index = int(query.data.split("_")[1])
    results = user_search_results.get(user_id, [])

    if not results or index >= len(results):
        await query.message.reply_text("خطا، دوباره سرچ کن.")
        return

    track = results[index]
    title = track.get("title", "نامشخص")
    url = track.get("url") or track.get("webpage_url", "")

    if not url:
        await query.message.reply_text("❌ لینک پیدا نشد، دوباره سرچ کن.")
        return

    msg = await query.message.reply_text(f"⬇️ دارم دانلود میکنم...\n🎵 {title}")

    try:
        mp3_path = f"song_{user_id}.mp3"
        ydl_opts = {
            "format": "bestaudio/best",
            "outtmpl": f"song_{user_id}.%(ext)s",
            "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3"}],
            "quiet": True
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

        await query.message.reply_audio(
            audio=open(mp3_path, "rb"),
            title=title
        )
        await msg.delete()

    except Exception as e:
        await msg.edit_text(f"❌ خطا: {e}")
    finally:
        if os.path.exists(f"song_{user_id}.mp3"):
            os.remove(f"song_{user_id}.mp3")

async def download_and_send(update, context, title, artist, msg):
    user_id = update.message.from_user.id
    search_query = f"scsearch1:{title} {artist}"
    mp3_path = f"song_{user_id}.mp3"

    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": f"song_{user_id}.%(ext)s",
        "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3"}],
        "quiet": True
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([search_query])

    await update.message.reply_audio(
        audio=open(mp3_path, "rb"),
        title=title,
        performer=artist
    )
    await msg.delete()

    if os.path.exists(mp3_path):
        os.remove(mp3_path)

def get_song(url):
    host = "reels-tiktok-shorts-song-recognition-api-shazam.p.rapidapi.com"
    api_url = "https://" + host + "/recognize/social/url"
    headers = {"x-rapidapi-key": RAPIDAPI_KEY, "x-rapidapi-host": host}
    response = requests.get(api_url, headers=headers, params={"url": url})
    return response.json()

async def song_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer("در حال جستجوی آهنگ...")

    url = user_urls.get(user_id)
    if not url:
        await query.message.reply_text("لینک پیدا نشد، دوباره ویدیو رو بفرست.")
        return

    msg = await query.message.reply_text("🔍 دارم آهنگ رو شناسایی میکنم...")

    try:
        song_data = get_song(url)
        track = song_data.get("track")

        if not track:
            await msg.edit_text("آهنگی پیدا نشد 😔")
            return

        title = track.get("title", "نامشخص")
        artist = track.get("subtitle", "نامشخص")

        await msg.edit_text(f"🎵 {title} - {artist}\n⬇️ دارم دانلود میکنم...")

        search_query = f"scsearch1:{title} {artist}"
        mp3_path = f"song_{user_id}.mp3"

        ydl_opts = {
            "format": "bestaudio/best",
            "outtmpl": f"song_{user_id}.%(ext)s",
            "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3"}],
            "quiet": True
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([search_query])

        await query.message.reply_audio(
            audio=open(mp3_path, "rb"),
            title=title,
            performer=artist
        )
        await msg.delete()

    except Exception as e:
        await msg.edit_text(f"❌ خطا: {e}")

    finally:
        mp3_path = f"song_{user_id}.mp3"
        if os.path.exists(mp3_path):
            os.remove(mp3_path)

async def handle_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if not await is_member(context.bot, user_id):
        await not_joined_message(update)
        return

    url = update.message.text.strip()
    if "instagram.com" not in url:
        await update.message.reply_text("فقط لینک اینستاگرام بفرست یا از /search استفاده کن.")
        return

    await update.message.reply_text("در حال دانلود...")

    ydl_opts = {
        "outtmpl": f"video_{user_id}.mp4",
        "format": "best[ext=mp4]/best",
        "noplaylist": True
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

        user_urls[user_id] = url

        keyboard = [
            [InlineKeyboardButton("کانال ما 📢", url="https://t.me/downloader_hamechi")],
            [InlineKeyboardButton("🎵 دریافت آهنگ", callback_data="get_song")]
        ]

        await update.message.reply_video(
            video=open(f"video_{user_id}.mp4", "rb"),
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    except Exception as e:
        await update.message.reply_text(f"خطا: {e}")

    finally:
        if os.path.exists(f"video_{user_id}.mp4"):
            os.remove(f"video_{user_id}.mp4")

app = ApplicationBuilder().token(TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("search", search_command))
app.add_handler(CallbackQueryHandler(check_join_callback, pattern="check_join"))
app.add_handler(CallbackQueryHandler(song_callback, pattern="get_song"))
app.add_handler(CallbackQueryHandler(download_callback, pattern="^dl_"))
app.add_handler(MessageHandler(filters.VOICE, handle_voice))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_link))
app.run_polling()
