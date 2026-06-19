import rubpy
import asyncio
import aiohttp
import os
import time

# تنظیمات از Environment Variables
SESSION_STRING = os.environ.get("SESSION_STRING")
DOWNLOAD_DIR = "/tmp/downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# ساخت کلاینت با session string
app = rubpy.Client("rubika_bot", session_string=SESSION_STRING)


def format_size(size_bytes):
    if size_bytes <= 0:
        return "نامشخص"
    elif size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"


def format_speed(bps):
    if bps < 1024:
        return f"{bps:.0f} B/s"
    elif bps < 1024 * 1024:
        return f"{bps / 1024:.1f} KB/s"
    else:
        return f"{bps / (1024 * 1024):.1f} MB/s"


def progress_bar(percent, length=14):
    filled = int(length * percent / 100)
    return "█" * filled + "░" * (length - filled)


async def download_and_delete(app, message, chat_id, index, total):
    """دانلود فایل، نمایش پیشرفت، و حذف از حافظه"""
    file_inline = message.file_inline
    filename = getattr(file_inline, 'file_name', None) or f"file_{int(time.time())}"
    file_size = getattr(file_inline, 'size', 0) or 0
    filepath = os.path.join(DOWNLOAD_DIR, filename)

    # پیام اولیه
    status_msg = await app.send_message(
        chat_id,
        f"📥 دانلود {index} از {total}\n\n"
        f"📄 {filename}\n"
        f"📦 حجم: {format_size(file_size)}\n"
        f"⏳ در حال شروع..."
    )
    status_msg_id = status_msg.message_id

    try:
        start_time = time.time()
        last_update = start_time
        downloaded = 0

        # دانلود با rubpy
        async def progress_callback(current, total_bytes):
            nonlocal downloaded, last_update
            downloaded = current
            now = time.time()

            if now - last_update >= 2:
                elapsed = now - start_time
                speed = current / elapsed if elapsed > 0 else 0

                if total_bytes and total_bytes > 0:
                    pct = (current / total_bytes) * 100
                    bar = progress_bar(pct)
                    text = (
                        f"📥 دانلود {index} از {total}\n\n"
                        f"📄 {filename}\n"
                        f"[{bar}] {pct:.1f}%\n"
                        f"📦 {format_size(current)} / {format_size(total_bytes)}\n"
                        f"⚡ {format_speed(speed)}"
                    )
                else:
                    text = (
                        f"📥 دانلود {index} از {total}\n\n"
                        f"📄 {filename}\n"
                        f"📦 {format_size(current)} دانلود شد\n"
                        f"⚡ {format_speed(speed)}"
                    )

                try:
                    await app.edit_message(chat_id, status_msg_id, text)
                except Exception:
                    pass

                last_update = now

        await app.download(
            file_inline,
            filepath,
            progress=progress_callback
        )

        elapsed = time.time() - start_time
        avg_speed = downloaded / elapsed if elapsed > 0 else 0
        actual_size = os.path.getsize(filepath) if os.path.exists(filepath) else file_size

        # پیام موفقیت
        await app.edit_message(
            chat_id,
            status_msg_id,
            f"✅ دانلود {index} از {total} تموم شد!\n\n"
            f"📄 {filename}\n"
            f"📦 حجم: {format_size(actual_size)}\n"
            f"⏱ زمان: {elapsed:.1f} ثانیه\n"
            f"⚡ میانگین سرعت: {format_speed(avg_speed)}"
        )

    except Exception as e:
        await app.edit_message(
            chat_id,
            status_msg_id,
            f"❌ خطا در دانلود {index} از {total}\n\n"
            f"📄 {filename}\n"
            f"🔴 {str(e)}"
        )
        filepath = None

    finally:
        # حذف فایل از حافظه بعد از دانلود
        if filepath and os.path.exists(filepath):
            try:
                os.remove(filepath)
            except Exception:
                pass

    return filepath


# صف دانلود هر چت
user_queues: dict[str, list] = {}
user_tasks: dict[str, asyncio.Task] = {}


async def process_queue(chat_id: str):
    queue = user_queues.get(chat_id, [])
    total = len(queue)

    # آپدیت total برای همه آیتم‌ها
    for i, item in enumerate(queue):
        item['index'] = i + 1
        item['total'] = total

    while queue:
        item = queue.pop(0)
        await download_and_delete(
            app,
            item['message'],
            chat_id,
            item['index'],
            item['total']
        )
        await asyncio.sleep(0.3)

    await app.send_message(
        chat_id,
        f"🎉 همه {total} فایل دانلود شدن و از حافظه پاک شدن!\n\n"
        f"📤 فایل دیگه‌ای داری بفرست."
    )

    user_tasks.pop(chat_id, None)
    user_queues.pop(chat_id, None)


@app.on_message_updates()
async def handler(message: rubpy.types.Updates):
    try:
        chat_id = message.chat_id

        # فقط پیام‌های خصوصی
        if not chat_id.startswith("u"):
            return

        # پیام خوش‌آمد
        if hasattr(message, 'text') and message.text:
            text = message.text.strip()
            if text in ['/start', 'سلام', 'شروع', 'هلو']:
                await app.send_message(
                    chat_id,
                    "👋 سلام!\n\n"
                    "📤 هر فایل یا ویدیویی که بخوای دانلود بشه بفرست.\n"
                    "📦 چند فایل هم‌زمان قبول می‌کنم!\n\n"
                    "⚡ با حداکثر سرعت دانلود می‌کنم و بعدش از حافظه پاک می‌کنم."
                )
            return

        # چک فایل
        if not hasattr(message, 'file_inline') or not message.file_inline:
            return

        # اضافه به صف
        if chat_id not in user_queues:
            user_queues[chat_id] = []

        user_queues[chat_id].append({
            'message': message,
            'index': len(user_queues[chat_id]) + 1,
            'total': len(user_queues[chat_id]) + 1
        })

        # اگه تسک فعال نیست، شروع کن
        task = user_tasks.get(chat_id)
        if not task or task.done():
            # یه ثانیه صبر کن شاید فایل‌های بیشتری بیان
            await asyncio.sleep(1)
            user_tasks[chat_id] = asyncio.create_task(process_queue(chat_id))

    except Exception as e:
        print(f"[ERROR] {e}")


if __name__ == "__main__":
    if not SESSION_STRING:
        print("❌ متغیر SESSION_STRING تنظیم نشده!")
        print("ابتدا فایل get_session.py رو لوکال اجرا کن.")
        exit(1)

    print("🤖 ربات دانلودر روبیکا شروع به کار کرد...")
    app.run()
