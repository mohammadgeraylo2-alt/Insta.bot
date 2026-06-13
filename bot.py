from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, MessageHandler, CommandHandler, CallbackQueryHandler, filters, ContextTypes
import yt_dlp
import requests
import os

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
        await query.message.reply_text("سلام! لینک اینستاگرام بفرست یا اسم آهنگ بنویس")
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
    )

def search_deezer(query):
    try:
        r = requests.get(
            "https://api.deezer.com/search",
            params={"q": query, "limit": 8},
            timeout=10
        )
        data = r.json()
        tracks = data.get("data", [])
        results = []
        for track in tracks:
            results.append({
                "title": track.get("title", "نامشخص"),
                "artist": track.get("artist", {}).get("name", "نامشخص"),
                "duration": track.get("duration", 0),
            })
        return results
    except Exception as e:
        print(f"Deezer error: {e}")
        return []

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
    artist = track.get("artist", "")
    search_query = f"{title} {artist}"

    msg = await query.message.reply_text(f"⬇️ دارم دانلود میکنم...\n🎵 {title} - {artist}")

    try:
        mp3_path = f"song_{user_id}.mp3"
        ydl_opts = {
            "format": "bestaudio/best",
            "outtmpl": f"song_{user_id}.%(ext)s",
            "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3"}],
            "quiet": True
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([f"scsearch1:{search_query}"])

        await query.message.reply_audio(
            audio=open(mp3_path, "rb"),
            title=title,
            performer=artist
        )
        await msg.delete()

    except Exception as e:
        await msg.edit_text(f"❌ خطا: {e}")
    finally:
        if os.path.exists(f"song_{user_id}.mp3"):
            os.remove(f"song_{user_id}.mp3")

async def download_and_send(update, context, title, artist, msg):
    user_id = update.message.from_user.id
    mp3_path = f"song_{user_id}.mp3"

    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": f"song_{user_id}.%(ext)s",
        "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3"}],
        "quiet": True
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([f"scsearch1:{title} {artist}"])

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

        mp3_path = f"song_{user_id}.mp3"
        ydl_opts = {
            "format": "bestaudio/best",
            "outtmpl": f"song_{user_id}.%(ext)s",
            "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3"}],
            "quiet": True
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([f"scsearch1:{title} {artist}"])

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

    text = update.message.text.strip()

    if "instagram.com" in text:
        await update.message.reply_text("در حال دانلود...")
        ydl_opts = {
            "outtmpl": f"video_{user_id}.mp4",
            "format": "best[ext=mp4]/best",
            "noplaylist": True
        }
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([text])

            user_urls[user_id] = text
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

    else:
        msg = await update.message.reply_text("🔍 دارم سرچ میکنم...")
        try:
            results = search_deezer(text)
            if not results:
                await msg.edit_text("نتیجه‌ای پیدا نشد 😔")
                return

            user_search_results[user_id] = results
            keyboard = []
            for i, track in enumerate(results[:8]):
                title = track.get("title", "نامشخص")[:30]
                artist = track.get("artist", "")[:15]
                duration = track.get("duration", 0)
                mins = int(duration) // 60 if duration else 0
                secs = int(duration) % 60 if duration else 0
                keyboard.append([InlineKeyboardButton(
                    f"🎵 {title} - {artist} ({mins}:{secs:02d})",
                    callback_data=f"dl_{i}"
                )])

            await msg.edit_text(
                "🎵 *نتایج سرچ:*",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        except Exception as e:
            await msg.edit_text(f"❌ خطا: {e}")

app = ApplicationBuilder().token(TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(CallbackQueryHandler(check_join_callback, pattern="check_join"))
app.add_handler(CallbackQueryHandler(song_callback, pattern="get_song"))
app.add_handler(CallbackQueryHandler(download_callback, pattern="^dl_"))
app.add_handler(MessageHandler(filters.VOICE, handle_voice))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_link))
app.run_polling()
        
