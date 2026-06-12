from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, MessageHandler, CommandHandler, CallbackQueryHandler, filters, ContextTypes
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
    keyboard = [
        [InlineKeyboardButton("عضویت در کانال 📢", url="https://t.me/downloader_hamechi")],
        [InlineKeyboardButton("عضو شدم ✅", callback_data="check_join")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "⛔️ برای استفاده از ربات باید عضو کانال ما بشی!\n\n"
        "بعد از عضویت روی دکمه عضو شدم بزن 👇",
        reply_markup=reply_markup
    )

async def check_join_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    if await is_member(context.bot, user_id):
        await query.answer("✅ عضویت تایید شد!")
        await query.message.reply_text(
            "👋 سلام خوش اومدی!\n\n"
            "با این ربات میتونی پست، ریلز و ویدیوهای اینستاگرام و یوتیوب رو دانلود کنی 📥\n\n"
            "فقط لینک رو برام بفرستی!"
        )
    else:
        a
