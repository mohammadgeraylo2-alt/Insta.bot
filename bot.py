from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, MessageHandler, CommandHandler, CallbackQueryHandler, filters, ContextTypes
import yt_dlp
import requests
import os
import base64

TOKEN = os.environ["BOT_TOKEN"]
RAPIDAPI_KEY = os.environ["RAPIDAPI_KEY"]
CHANNEL = "@downloader_hamechi"
CAPTION = "🎵 ربات موزیک یاب و دانلود از اینستاگرام\n @downloader_hamechi"
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
        "*سلام!*\n\n"
        "*برای استفاده از ربات، اول باید عضو کانال ما بشی*\n\n"
        "*بعد از عضویت روی دکمه عضو شدم بزن*",
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
        "*سلام*\n\n"
        "*لینک پست اینستاگرام بفرست* برای دانلود ویدیو\n"
        "*لینک استوری اینستاگرام بفرست* برای دانلود استوری\n"
        "*لینک پینترست بفرست* برای دانلود ویدیو یا عکس\n"
        "*اسم آهنگ بنویس* برای سرچ و دانلود\n"
        "*ویس بفرست* برای شناسایی آهنگ\n"
        "*ویدیو فوروارد کن* برای دریافت آهنگش",
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
    top_artist_id = None
    top_artist_name = None

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

    try:
        r = requests.get(
            "https://api.deezer.com/search",
            params={"q": query, "limit": 10},
            timeout=8
        )
        tracks = r.json().get("data", [])

        artist_scores = {}
        for track in tracks:
            a_id = track.get("artist", {}).get("id")
            a_name = track.get("artist", {}).get("name", "")
            if a_id and a_id not in artist_scores:
                score = fuzzy_score(query, a_name)
                artist_scores[a_id] = {"name": a_name, "score": score}

        if artist_scores:
            best_id = max(artist_scores, key=lambda x: artist_scores[x]["score"])
            top_artist_id = best_id
            top_artist_name = artist_scores[best_id]["name"]

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
    return results[:10], top_artist_id, top_artist_name


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

    msg = await update.message.reply_text("دارم آهنگ رو شناسایی میکنم...")

    try:
        voice = await update.message.voice.get_file()
        voice_path = f"voice_{user_id}.ogg"
        await voice.download_to_drive(voice_path)

        with open(voice_path, "rb") as f:
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
            await msg.edit_text("آهنگی شناسایی نشد")
            return

        title = track.get("title", "نامشخص")
        artist = track.get("subtitle", "نامشخص")

        await msg.edit_text(f"*{title}*\n*{artist}*\nدارم دانلود میکنم...", parse_mode="Markdown")
        await download_and_send(update, context, title, artist, msg)

    except Exception as e:
        await msg.edit_text(f"خطا: {e}")
    finally:
        if os.path.exists(f"voice_{user_id}.ogg"):
            os.remove(f"voice_{user_id}.ogg")


async def handle_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if not await is_member(context.bot, user_id):
        await not_joined_message(update)
        return

    msg = await update.message.reply_text("دارم آهنگ ویدیو رو شناسایی میکنم...")

    try:
        video = update.message.video or update.message.document
        file = await video.get_file()
        file_url = file.file_path

        host = "reels-tiktok-shorts-song-recognition-api-shazam.p.rapidapi.com"
        api_url = f"https://{host}/recognize/social/url"
        headers = {"x-rapidapi-key": RAPIDAPI_KEY, "x-rapidapi-host": host}
        r = requests.get(api_url, headers=headers, params={"url": file_url})
        data = r.json()
        track = data.get("track")

        if not track:
            await msg.edit_text("آهنگی شناسایی نشد")
            return

        title = track.get("title", "نامشخص")
        artist = track.get("subtitle", "نامشخص")

        await msg.edit_text(f"*{title}*\n*{artist}*\nدارم دانلود میکنم...", parse_mode="Markdown")
        await download_and_send(update, context, title, artist, msg)

    except Exception as e:
        await msg.edit_text(f"خطا: {e}")


async def download_and_send(update, context, title, artist, msg):
    user_id = update.message.from_user.id
    mp3_path = f"song_{user_id}.mp3"

    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": f"song_{user_id}.%(ext)s",
        "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3"}],
        "quiet": True,
        "noplaylist": True
    }

    downloaded = False
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([f"scsearch1:{title} {artist}"])
        downloaded = True
    except:
        pass

    if not downloaded:
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([f"ytsearch1:{title} {artist}"])
            downloaded = True
        except:
            pass

    if not downloaded:
        await msg.edit_text("دانلود ممکن نشد، دوباره امتحان کن.")
        return

    await update.message.reply_audio(
        audio=open(mp3_path, "rb"),
        title=title,
        performer=artist,
        caption=CAPTION
    )
    await msg.delete()

    if os.path.exists(mp3_path):
        os.remove(mp3_path)


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

    msg = await query.message.reply_text(f"دارم دانلود میکنم...\n{title} - {artist}")

    mp3_path = f"song_{user_id}.mp3"
    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": f"song_{user_id}.%(ext)s",
        "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3"}],
        "quiet": True,
        "noplaylist": True
    }

    downloaded = False
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            if url:
                ydl.download([url])
            else:
                ydl.download([f"scsearch1:{title} {artist}"])
        downloaded = True
    except:
        pass

    if not downloaded:
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([f"ytsearch1:{title} {artist}"])
            downloaded = True
        except:
            pass

    if not downloaded:
        await msg.edit_text("دانلود ممکن نشد، دوباره امتحان کن.")
        return

    try:
        await query.message.reply_audio(
            audio=open(mp3_path, "rb"),
            title=title,
            performer=artist,
            caption=CAPTION
        )
        await msg.delete()
    except Exception as e:
        await msg.edit_text(f"خطا: {e}")
    finally:
        if os.path.exists(mp3_path):
            os.remove(mp3_path)


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

    msg = await query.message.reply_text(f"دارم آهنگهای {artist_name} رو میگیرم...")

    tracks = get_artist_tracks(artist_id)
    if not tracks:
        await msg.edit_text("آهنگی پیدا نشد")
        return

    user_search_results[user_id] = tracks

    keyboard = []
    for i, track in enumerate(tracks):
        title = track.get("title", "نامشخص")[:28]
        artist = track.get("artist", "")[:15]
        keyboard.append([InlineKeyboardButton(
            f"{title} - {artist}",
            callback_data=f"dl_{i}"
        )])

    await msg.delete()
    await query.message.reply_text(
        f"*همه آهنگهای {artist_name}:*",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def song_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer("در حال جستجوی آهنگ...")

    msg = await query.message.reply_text("دارم آهنگ رو شناسایی میکنم...")

    try:
        target_msg = query.message.reply_to_message
        if not target_msg:
            target_msg = query.message

        video = None
        if target_msg and target_msg.video:
            video = target_msg.video
        elif target_msg and target_msg.document:
            video = target_msg.document

        if not video:
            await msg.edit_text("ویدیو پیدا نشد، دوباره بفرست.")
            return

        file = await video.get_file()
        file_url = file.file_path

        host = "reels-tiktok-shorts-song-recognition-api-shazam.p.rapidapi.com"
        api_url = f"https://{host}/recognize/social/url"
        headers = {"x-rapidapi-key": RAPIDAPI_KEY, "x-rapidapi-host": host}
        r = requests.get(api_url, headers=headers, params={"url": file_url})
        data = r.json()
        track = data.get("track")

        if not track:
            await msg.edit_text("آهنگی پیدا نشد 😔")
            return

        title = track.get("title", "نامشخص")
        artist = track.get("subtitle", "نامشخص")
        await msg.edit_text(f"{title} - {artist}\nدارم دانلود میکنم...")

        mp3_path = f"song_{user_id}.mp3"
        ydl_opts = {
            "format": "bestaudio/best",
            "outtmpl": f"song_{user_id}.%(ext)s",
            "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3"}],
            "quiet": True,
            "noplaylist": True
        }

        downloaded = False
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([f"scsearch1:{title} {artist}"])
            downloaded = True
        except:
            pass

        if not downloaded:
            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.download([f"ytsearch1:{title} {artist}"])
                downloaded = True
            except:
                pass

        if not downloaded:
            await msg.edit_text("دانلود ممکن نشد.")
            return

        await query.message.reply_audio(
            audio=open(mp3_path, "rb"),
            title=title,
            performer=artist,
            caption=CAPTION
        )
        await msg.delete()

    except Exception as e:
        await msg.edit_text(f"خطا: {e}")
    finally:
        if os.path.exists(f"song_{user_id}.mp3"):
            os.remove(f"song_{user_id}.mp3")


async def handle_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if not await is_member(context.bot, user_id):
        await not_joined_message(update)
        return

    text = update.message.text.strip()

    if "instagram.com" in text:
        if "/stories/" in text:
            msg = await update.message.reply_text("دارم استوری رو دانلود میکنم...")
            try:
                host = "instagram-downloader-download-instagram-stories-videos4.p.rapidapi.com"
                headers = {
                    "x-rapidapi-key": RAPIDAPI_KEY,
                    "x-rapidapi-host": host
                }
                r = requests.get(
                    f"https://{host}/convert",
                    headers=headers,
                    params={"url": text},
                    timeout=40
                )
                data = r.json()

                video_url = None
                if isinstance(data, dict):
                    media = data.get("media", [])
                    if media:
                        video_url = media[0].get("url")
                    if not video_url:
                        video_url = (
                            data.get("url") or
                            data.get("video_url") or
                            data.get("media_url") or
                            data.get("download_url")
                        )
                elif isinstance(data, list) and data:
                    video_url = data[0].get("url") or data[0].get("video_url")

                if not video_url:
                    await msg.edit_text("استوری پیدا نشد")
                    return

                video_data = requests.get(video_url, timeout=40).content
                path = f"story_{user_id}.mp4"
                with open(path, "wb") as f:
                    f.write(video_data)

                keyboard = [
                    [InlineKeyboardButton("کانال ما", url="https://t.me/downloader_hamechi")],
                    [InlineKeyboardButton("دریافت آهنگ", callback_data="get_song")]
                ]
                user_urls[user_id] = text
                await update.message.reply_video(
                    video=open(path, "rb"),
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
                await msg.delete()
                if os.path.exists(path):
                    os.remove(path)

            except Exception as e:
                await msg.edit_text(f"خطا: {e}")

        else:
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
                    [InlineKeyboardButton("کانال ما", url="https://t.me/downloader_hamechi")],
                    [InlineKeyboardButton("دریافت آهنگ", callback_data="get_song")]
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

    elif "pinterest.com" in text or "pin.it" in text:
        msg = await update.message.reply_text("دارم از پینترست دانلود میکنم...")
        import glob
        try:
            keyboard = [[InlineKeyboardButton("کانال ما 📢", url="https://t.me/downloader_hamechi")]]
            sent = False

            # اول تلاش برای دانلود ویدیو با yt-dlp
            try:
                ydl_opts = {
                    "outtmpl": f"pinterest_{user_id}.%(ext)s",
                    "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
                    "merge_output_format": "mp4",
                    "noplaylist": True,
                    "quiet": True,
                }
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.extract_info(text, download=True)

                matches = glob.glob(f"pinterest_{user_id}.*")
                if matches:
                    file_path = matches[0]
                    ext = file_path.rsplit(".", 1)[-1]
                    if ext in ("mp4", "mov", "webm"):
                        await update.message.reply_video(
                            video=open(file_path, "rb"),
                            caption=CAPTION,
                            reply_markup=InlineKeyboardMarkup(keyboard),
                            supports_streaming=True
                        )
                        sent = True
            except Exception:
                pass

            # اگه ویدیو نبود، عکس رو با RapidAPI بگیر
            if not sent:
                media_url = None

                # API 1: JustMobi
                try:
                    host1 = "pinterest-downloader-download-pinterest-image-video-and-reels.p.rapidapi.com"
                    r1 = requests.get(
                        f"https://{host1}/download",
                        headers={"x-rapidapi-key": RAPIDAPI_KEY, "x-rapidapi-host": host1},
                        params={"url": text},
                        timeout=20
                    )
                    d1 = r1.json()
                    if isinstance(d1, dict):
                        media_url = d1.get("url") or d1.get("image") or d1.get("media_url")
                        if not media_url and isinstance(d1.get("data"), dict):
                            media_url = d1["data"].get("url") or d1["data"].get("image")
                        if not media_url and isinstance(d1.get("data"), list) and d1["data"]:
                            media_url = d1["data"][0].get("url")
                    elif isinstance(d1, list) and d1:
                        media_url = d1[0].get("url")
                except Exception:
                    pass

                # API 2: slim-python
                if not media_url:
                    try:
                        host2 = "pinterest-downloader-download-image-video-and-pinterest-ideapin.p.rapidapi.com"
                        r2 = requests.get(
                            f"https://{host2}/download",
                            headers={"x-rapidapi-key": RAPIDAPI_KEY, "x-rapidapi-host": host2},
                            params={"url": text},
                            timeout=20
                        )
                        d2 = r2.json()
                        if isinstance(d2, dict):
                            media_url = d2.get("url") or d2.get("image") or d2.get("download_url")
                            if not media_url and isinstance(d2.get("data"), dict):
                                media_url = d2["data"].get("url") or d2["data"].get("image")
                            if not media_url and isinstance(d2.get("data"), list) and d2["data"]:
                                media_url = d2["data"][0].get("url")
                        elif isinstance(d2, list) and d2:
                            media_url = d2[0].get("url")
                    except Exception:
                        pass

                # API 3: vikas5914
                if not media_url:
                    try:
                        host3 = "pinterest-video-and-image-downloader.p.rapidapi.com"
                        r3 = requests.get(
                            f"https://{host3}/download",
                            headers={"x-rapidapi-key": RAPIDAPI_KEY, "x-rapidapi-host": host3},
                            params={"url": text},
                            timeout=20
                        )
                        d3 = r3.json()
                        if isinstance(d3, dict):
                            media_url = d3.get("url") or d3.get("image") or d3.get("download_url")
                            if not media_url and isinstance(d3.get("data"), dict):
                                media_url = d3["data"].get("url") or d3["data"].get("image")
                            if not media_url and isinstance(d3.get("data"), list) and d3["data"]:
                                media_url = d3["data"][0].get("url")
                        elif isinstance(d3, list) and d3:
                            media_url = d3[0].get("url")
                    except Exception:
                        pass

                if not media_url:
                    debug = []
                    try: debug.append(f"API1: {str(d1)[:200]}")
                    except: debug.append("API1: خطا")
                    try: debug.append(f"API2: {str(d2)[:200]}")
                    except: debug.append("API2: خطا")
                    try: debug.append(f"API3: {str(d3)[:200]}")
                    except: debug.append("API3: خطا")
                    await msg.edit_text("\n\n".join(debug))
                    return

                dl_content = requests.get(media_url, timeout=30).content
                img_path = f"pinterest_{user_id}.jpg"
                with open(img_path, "wb") as fp:
                    fp.write(dl_content)

                await update.message.reply_photo(
                    photo=open(img_path, "rb"),
                    caption=CAPTION,
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
                sent = True

            if sent:
                await msg.delete()

        except Exception as e:
            await msg.edit_text(f"خطا در دانلود پینترست: {e}")
        finally:
            for f in glob.glob(f"pinterest_{user_id}.*"):
                os.remove(f)

    else:
        msg = await update.message.reply_text("دارم سرچ میکنم...")
        try:
            results, artist_id, artist_name = search_songs(text)
            if not results:
                await msg.edit_text("نتیجه‌ای پیدا نشد")
                return

            user_search_results[user_id] = results

            if artist_id:
                user_artist_data[user_id] = {"id": artist_id, "name": artist_name}

            keyboard = []
            for i, track in enumerate(results):
                title = track.get("title", "نامشخص")[:28]
                artist = track.get("artist", "")[:15]
                keyboard.append([InlineKeyboardButton(
                    f"{title} - {artist}",
                    callback_data=f"dl_{i}"
                )])

            if artist_id and artist_name:
                keyboard.append([InlineKeyboardButton(
                    f"همه آهنگهای {artist_name}",
                    callback_data="all_songs"
                )])

            await msg.edit_text(
                "*نتایج سرچ:*",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        except Exception as e:
            await msg.edit_text(f"خطا: {e}")


app = ApplicationBuilder().token(TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(CallbackQueryHandler(check_join_callback, pattern="check_join"))
app.add_handler(CallbackQueryHandler(song_callback, pattern="get_song"))
app.add_handler(CallbackQueryHandler(all_songs_callback, pattern="all_songs"))
app.add_handler(CallbackQueryHandler(download_callback, pattern="^dl_"))
app.add_handler(MessageHandler(filters.VOICE, handle_voice))
app.add_handler(MessageHandler(filters.VIDEO | filters.Document.VIDEO, handle_video))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_link))
app.run_polling()
