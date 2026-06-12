from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, MessageHandler, CommandHandler, filters, ContextTypes
import yt_dlp
import os

TOKEN = os.environ["BOT_TOKEN"]
CHANNEL = "@downloader_hamechi"

async def is_member(bot, user_id):
    try:
        member = await bot.get_chat_member(CHANNEL, user_id)
        return member.status in ["member", "administrator", "creator"]
    except:
        return False

async def not_joined_message(update):
    keyboard = [[InlineKeyboardButton("عضویت در کانال 📢", url=f"https://t.me/downloader_hamechi")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "⛔️ برای استفاده از ربات باید عضو کانال ما بشی!\n\n"
        "بعد از عضویت دوباره امتحان کن 👇",
        reply_markup=reply_markup
    )

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if not await is_member(context.bot, user_id):
        await not_joined_message(update)
        return
    await update.message.reply_text(
        "👋 سلام خوش اومدی!\n\n"
        "با این ربات میتونی پست، ریلز و ویدیوهای اینستاگرام رو دانلود کنی 📥\n\n"
        "فقط لینک پست رو برام بفرستی!"
    )

async def handle_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if not await is_member(context.bot, user_id):
        await not_joined_message(update)
        return

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
app.add_handler(CommandHandler("start", start))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_link))
app.run_polling()
