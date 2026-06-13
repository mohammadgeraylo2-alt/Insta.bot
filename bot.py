from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters
)

import aiohttp
import os

TOKEN = os.getenv("BOT_TOKEN")
CHANNEL = "@downloader_hamechi"


async def is_member(bot, user_id):
    try:
        member = await bot.get_chat_member(CHANNEL, user_id)
        return member.status in [
            "member",
            "administrator",
            "creator"
        ]
    except Exception:
        return False


async def send_join_message(message):
    keyboard = [
        [
            InlineKeyboardButton(
                "عضویت در کانال 📢",
                url="https://t.me/downloader_hamechi"
            )
        ],
        [
            InlineKeyboardButton(
                "عضو شدم ✅",
                callback_data="check_join"
            )
        ]
    ]

    await message.reply_text(
        "برای استفاده از ربات ابتدا عضو کانال شوید.",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if not await is_member(context.bot, user_id):
        await send_join_message(update.message)
        return

    await update.message.reply_text(
        "لینک اینستاگرام یا یوتیوب را ارسال کنید."
    )


async def check_join_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id

    if await is_member(context.bot, user_id):
        await query.message.reply_text(
            "عضویت تایید شد ✅\nلینک را ارسال کنید."
        )
    else:
        await query.answer(
            "هنوز عضو کانال نشده‌اید.",
            show_alert=True
        )


async def download_from_cobalt(url):
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json"
    }

    payload = {
        "url": url
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(
            "https://api.cobalt.tools/",
            json=payload,
            headers=headers,
            timeout=30
        ) as response:

            text = await response.text()

            try:
                data = await response.json()
            except Exception:
                return {
                    "error": text
                }

            return data


async def handle_link(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    user_id = update.effective_user.id

    if not await is_member(context.bot, user_id):
        await send_join_message(update.message)
        return

    url = update.message.text.strip()

    if not any(x in url for x in [
        "instagram.com",
        "youtube.com",
        "youtu.be"
    ]):
        await update.message.reply_text(
            "فقط لینک اینستاگرام یا یوتیوب ارسال کنید."
        )
        return

    msg = await update.message.reply_text(
        "در حال پردازش..."
    )

    try:
        data = await download_from_cobalt(url)

        print("API RESPONSE:", data)

        if "error" in data:
            await msg.edit_text(
                f"خطا:\n{data['error']}"
            )
            return

        status = data.get("status")

        if status in ["stream", "redirect"]:
            await update.message.reply_video(
                video=data["url"]
            )

        elif status == "picker":
            if data.get("picker"):
                await update.message.reply_video(
                    video=data["picker"][0]["url"]
                )
            else:
                await msg.edit_text(
                    "فایلی پیدا نشد."
                )

        else:
            await msg.edit_text(
                f"پاسخ نامعتبر:\n{data}"
            )

    except Exception as e:
        await msg.edit_text(
            f"خطا:\n{str(e)}"
        )


app = ApplicationBuilder().token(TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(
    CallbackQueryHandler(
        check_join_callback,
        pattern="check_join"
    )
)
app.add_handler(
    MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        handle_link
    )
)

app.run_polling()
