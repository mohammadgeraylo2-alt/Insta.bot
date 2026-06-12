from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes
import yt_dlp
import os

TOKEN = os.environ["BOT_TOKEN"]

async def handle_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text.strip()

    if "instagram.com" not in url:
        await update.message.reply_text("لینک اینستاگرام بفرست.")
        return

    await update.message.reply_text("در حال دانلود...")

    ydl_opts = {
        'outtmpl': 'video.mp4',
        'format': 'mp4',
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

        await update.message.reply_video(video=open('video.mp4', 'rb'))

    except Exception as e:
        await update.message.reply_text(f"خطا: {e}")

    finally:
        if os.path.exists('video.mp4'):
            os.remove('video.mp4')

app = ApplicationBuilder().token(TOKEN).build()
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_link))
app.run_polling()
