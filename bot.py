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
user_artist_data = {}

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

def fuzzy_score(query, title):
    q = query.lower()
    t = title.lower()
    score = 0
    if q == t:
        return 100
    if t.startswith(q) or q.startswith(t):
        score += 50
    q_words = set(q.split())
    t_words = set(t.split())
    common = q_words & t_words
    score += len(common) * 20
    q_chars = set(q.replace(" ", ""))
    t_chars = set(t.replace(" ", ""))
    char_overlap = len(q_chars & t_chars) / max(len(q_chars), len(t_chars), 1)
    score += int(char_overlap * 30)
    return score

def search_songs(query):
    results = []
    seen_titles = set()

    # سرچ SoundCloud
    ydl_opts = {"quiet": True, "extract_flat": True}
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            result = ydl.extract_info(f"scsearch10:{query}", download=False)
            for entry in result.get("entries", []):
                title = entry.get("title", "")
                key = title.lower().strip()
                if key not in seen_titles:
                    seen_titles.add(key)
                    results.append({
                        "title": title,
                        "artist": entry.get("uploader", ""),
                        "duration": entry.get("duration", 0),
                        "url": entry.get("url") or entry.get("webpage_url", ""),
                        "score": fuzzy_score(query, title)
                    })
    except:
        pass

    # سرچ Deezer
    top_artist_id = None
    top_artist_name = None
    try:
        r = requests.get(
            "https://api.deezer.com/search",
            params={"q": query, "limit": 10},
            timeout=8
        )
        tracks = r.json().get("data", [])

        # پیدا کردن آرتیست با بیشترین تکرار در نتایج
        artist_counter = {}
        for track in tracks:
            a_id = track.get("artist", {}).get("id")
            a_name = track.get("artist", {}).get("name", "")
            if a_id:
                if a_id not in artist_counter:
                    artist_counter[a_id] = {"count": 0, "name": a_name}
                artist_counter[a_id]["count"] += 1

        if artist_counter:
            best_artist_id = max(artist_counter, key=lambda x: artist_counter[x]["count"])
            top_artist_id = best_artist_id
            top_artist_name = artist_counter[best_artist_id]["name"]

        for track in tracks:
            title = track.get("title", "")
            artist = track.get("artist", {}).get("name", "")
            key = f"{title} {artist}".lower().strip()
            if key not in seen_titles:
                seen_titles.add(key)
                results.append({
                    "title": title,
                    "artist": artist,
                    "duration": track.get("duration", 0),
                    "url": None,
                    "score": fuzzy_score(query, f"{title} {artist}")
                })
    except:
        pass

    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:5], top_artist_id, top_artist_name

def get_artist_tracks(artist_id):
    try:
        r = requests.get(
            f"https://api.deezer.com/artist/{artist_id}/top",
            params={"limit": 50},
            timeout=8
        )
        tracks = r.json().get("data", [])
        results = []
        for track in tracks:
            results.append({
                "title": track.get("title", ""),
                "artist": track.get("artist", {}).get("name", ""),
                "duration": track.get("duration", 0),
                "url": None,
            })
        return results
    except:
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
        r = requests.post(f"https://{host}/songs/v2/detect", headers=headers, data=audio_b64)
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
    url = track.get("url")

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
            if url:
                ydl.download([url])
            else:
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
        if os.path.exists(f"song_{user_id}.mp3"):
            os.remove(f"song_{user_id}.mp3")

async def all_songs_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer("در حال دریافت لیست...")

    artist_data = user_artist_data.get(user_id)
    if not artist_data:
        await query.message.reply_text("خطا، دوباره سرچ کن.")
        return

    artist_id = artist_data["id"]
    artist_name = artist_data["name"]

    msg = await query.message.reply_text(f"🎤 دارم آهنگ‌های {artist_name} رو میگیرم...")

    tracks = get_artist_tracks(artist_id)
    if not tracks:
        await msg.edit_text("آهنگی پیدا نشد 😔")
        return

    user_search_results[user_id] = tracks

    keyboard = []
    for i, track in enumerate(tracks):
        title = track.get("title", "نامشخص")[:28]
        artist = track.get("artist", "")[:15]
        keyboard.append([InlineKeyboardButton(
            f"🎵 {title} - {artist}",
            callback_data=f"dl_{i}"
        )])

    await msg.delete()
    await query.message.reply_text(
        f"🎤 *همه آهنگ‌های {artist_name}:*",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

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
            results, artist_id, artist_name = search_songs(text)
            if not results:
                await msg.edit_text("نتیجه‌ای پیدا نشد 😔")
                return

            user_search_results[user_id] = results

            if artist_id:
                user_artist_data[user_id] = {"id": artist_id, "name": artist_name}

            keyboard = []
            for i, track in enumerate(results):
                title = track.get("title", "نامشخص")[:28]
                artist = track.get("artist", "")[:15]
                keyboard.append([InlineKeyboardButton(
                    f"🎵 {title} - {artist}",
                    callback_data=f"dl_{i}"
                )])

            if artist_id and artist_name:
                keyboard.append([InlineKeyboardButton(
                    f"🎤 همه آهنگ‌های {artist_name}",
                    callback_data="all_songs"
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
app.add_handler(CallbackQueryHandler(all_songs_callback, pattern="all_songs"))
app.add_handler(CallbackQueryHandler(download_callback, pattern="^dl_"))
app.add_handler(MessageHandler(filters.VOICE, handle_voice))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_link))
app.run_polling()
