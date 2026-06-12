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
    keyboard = [
        [InlineKeyboardButton("عضویت در کانال 📢", url="https://t.me/downloader_hamechi")],
        [InlineKeyboardButton("عضو شدم ✅", callback_data="check_join")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "عضو کانال ما بشی!\n\nبعد از عضویت روی دکمه عضو شدم بزن",
        reply_markup=reply_markup
    )

async def check_join_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    if await is_member(context.bot, user_id):
        await query.answer("عضویت تایید شد!")
        await query.message.reply_text("سلام! لینک اینستاگرام یا یوتیوب بفرست")
    else:
        await query.answer("هنوز عضو نشدی!", show_alert=True)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if not await is_member(context.bot, user_id):
        await not_joined_message(update)
        return
    await update.message.reply_text("سلام! لینک اینستاگرام یا یوتیوب بفرست")

async def handle_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if not await is_member(context.bot, user_id):
        await not_joined_message(update)
        return
    url = update.message.text.strip()
    if "youtube.com" in url or "youtu.be" in url:
        await update.message.reply_text("در حال دانلود از یوتیوب...")
        try:
            headers = {
                "x-rapidapi-key": RAPIDAPI_KEY,
                "x-rapidapi-host": "hd-video-downloader.p.rapidapi.com"
            }
            params = {"url": url, "quality": "720"}
            response = requests.get("https://hd-video-downloader.p.rapidapi.com/api/youtube/download", headers=headers, params=params)
            data = response.json()
            video_url = data.get("url") or data.get("link") or data.get("download_url") or data.get("downloadUrl")
            if video_url:
                await update.message.reply_video(video=video_url)
            else:
                await update.message.reply_text(f"response: {data}")
        except Exception as e:
            await update.message.reply_text(f"خطا: {e}")
        return
    if "instagram.com" not in url:
        await update.message.reply_text("لینک اینستاگرام یا یوتیوب بفرست.")
        return
    await update.message.reply_text("در حال دانلود...")
    ydl_opts = {"outtmpl": "video.mp4", "format": "mp4"}
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
        await update.message.reply_video(video=open("video.mp4", "rb"))
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
