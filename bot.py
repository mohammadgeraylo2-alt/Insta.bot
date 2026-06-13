from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, MessageHandler, CommandHandler, CallbackQueryHandler, filters, ContextTypes
import yt_dlp
import requests
import os

TOKEN = os.environ["BOT_TOKEN"]
RAPIDAPI_KEY = os.environ["RAPIDAPI_KEY"]
CHANNEL = "@downloader_hamechi"
user_urls = {}

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
    await update.message.reply_text("عضو کانال بشی تا ربات کار کنه", reply_markup=InlineKeyboardMarkup(keyboard))

async def check_join_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    if await is_member(context.bot, user_id):
        await query.answer("عضویت تایید شد")
        await query.message.reply_text("سلام! لینک اینستاگرام بفرست")
    else:
        await query.answer("هنوز عضو نشدی", show_alert=True)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if not await is_member(context.bot, user_id):
        await not_joined_message(update)
        return
    await update.message.reply_text("سلام! لینک اینستاگرام بفرست")

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

        search_query = f"{title} {artist} official audio"
        mp3_path = f"song_{user_id}.mp3"

        ydl_opts = {
            "format": "bestaudio/best",
            "outtmpl": f"song_{user_id}.%(ext)s",
            "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3"}],
            "default_search": "ytsearch1",
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
        await msg.edit_text("❌ دانلود آهنگ ناموفق بود.")

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
        await update.message.reply_text("فقط لینک اینستاگرام بفرست.")
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
app.add_handler(CallbackQueryHandler(check_join_callback, pattern="check_join"))
app.add_handler(CallbackQueryHandler(song_callback, pattern="get_song"))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_link))
app.run_polling()
