from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, MessageHandler, CommandHandler, CallbackQueryHandler, filters, ContextTypes
import yt_dlp
import requests
import os

TOKEN = os.environ["BOT_TOKEN"]
RAPIDAPI_KEY = os.environ["RAPIDAPI_KEY"]
CHANNEL = "@downloader_hamechi"

async def is_member(bot, user_id):
    try:
        member = await bot.get_chat_member(CHANNEL, user_id)
        return member.status in ["member", "administrator", "creator"]
    except:
        return False

async def not_joined_message(update):
    keyboard = [[InlineKeyboardButton("عضویت در کانال", url="https://t.me/downloader_hamechi")],[InlineKeyboardButton("عضو شدم", callback_data="check_join")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("عضو کانال بشی تا ربات کار کنه", reply_markup=reply_markup)

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

async def get_song(url):
    headers = {
        "x-rapidapi-key": RAPIDAPI_KEY,
        "x-rapidapi-host": "reels-tiktok-shorts-song-recognition-api-shazam.p.rapidapi.com"
    }
    params = {"url": url}
    response = requests.get("https://reels-tiktok-shorts-song-recognition-api-shazam.p.rapidapi.com/recognize/social", headers=headers, params=params)
    return response.json()

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
    ydl_opts = {"outtmpl": "video.mp4", "format": "best[ext=mp4]/best", "noplaylist": True}
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
        keyboard = [[InlineKeyboardButton("کانال ما 📢", url="https://t.me/downloader_hamechi")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_video(video=open("video.mp4", "rb"), reply_markup=reply_markup)
        try:
            song_data = await get_song(url)
            track = song_data.get("track") or song_data.get("song")
            if track:
                title = track.get("title") or track.get("name", "نامشخص")
                artist = track.get("subtitle") or track.get("artist", "نامشخص")
                await update.message.reply_text(f"🎵 آهنگ: {title}\n👤 خواننده: {artist}")
        except:
            pass
    except Exception as e:
        await update.message.reply_text(f"خطا: {e}")
    finally:
        if os.path.exists("video.mp4"):
            os.remove("video.mp4")

app = ApplicationBuilder().token(TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(CallbackQueryHandler(check_join_callback, pattern="check_join"))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_link))
app.run_polling()
