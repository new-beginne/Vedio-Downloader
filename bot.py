import os
import time
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import yt_dlp
import threading
from queue import Queue

# 🔐 Token from environment (SAFE)
BOT_TOKEN = os.getenv("BOT_TOKEN")
bot = telebot.TeleBot(BOT_TOKEN)

# ==============================
# USER DATA & RATE LIMIT
# ==============================
user_data = {}
user_last = {}

# ==============================
# QUEUE SYSTEM
# ==============================
task_queue = Queue()

def worker():
    while True:
        data = task_queue.get()
        if data is None:
            break
        download_and_send(*data)
        task_queue.task_done()

# Start 2 worker threads
for _ in range(2):
    t = threading.Thread(target=worker, daemon=True)
    t.start()

# ==============================
# PROGRESS HOOK
# ==============================
def progress_hook(d, chat_id, msg_id):
    if d['status'] == 'downloading':
        percent = d.get('_percent_str', '').strip()
        speed = d.get('_speed_str', '')
        eta = d.get('_eta_str', '')

        text = f"📥 Downloading...\n{percent}\n⚡ {speed} | ⏳ {eta}"

        try:
            bot.edit_message_text(text, chat_id, msg_id)
        except:
            pass

# ==============================
# BASE YT-DLP OPTIONS
# ==============================
def base_opts(chat_id=None, msg_id=None):
    opts = {
        'quiet': True,
        'noplaylist': True,
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
            'Accept-Language': 'en-US,en;q=0.9',
        },
        'extractor_args': {
            'youtube': {
                'player_client': ['android', 'web']
            }
        },
        'sleep_interval': 2,
        'max_sleep_interval': 5,
        'retries': 10,
        'fragment_retries': 10,
    }
    if chat_id and msg_id:
        opts['progress_hooks'] = [lambda d: progress_hook(d, chat_id, msg_id)]
    return opts

# ==============================
# START COMMAND
# ==============================
@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.reply_to(message,
        "👋 Welcome!\n\n"
        "Send any video/playlist link.\n"
        "⚠️ Some videos may fail due to YouTube restrictions."
    )

# ==============================
# LINK HANDLER + RATE LIMIT
# ==============================
@bot.message_handler(func=lambda message: message.text.startswith('http'))
def handle_link(message):
    user_id = message.from_user.id
    now = time.time()

    if user_id in user_last and now - user_last[user_id] < 20:
        bot.reply_to(message, "⏳ Please wait 20 seconds before next request.")
        return

    user_last[user_id] = now

    chat_id = message.chat.id
    url = message.text
    user_data[chat_id] = {'url': url}

    markup = InlineKeyboardMarkup(row_width=1)
    markup.add(
        InlineKeyboardButton("⚡ Best Quality", callback_data="opt1"),
        InlineKeyboardButton("🇧🇩 Video + Bangla Sub", callback_data="opt2"),
        InlineKeyboardButton("🎬 Choose Quality", callback_data="opt3"),
        InlineKeyboardButton("🎵 MP3 Audio", callback_data="opt4"),
        InlineKeyboardButton("📂 Playlist", callback_data="opt5"),
        InlineKeyboardButton("🔗 Direct Link", callback_data="opt6")
    )

    bot.reply_to(message, "Choose download option:", reply_markup=markup)

# ==============================
# CALLBACK HANDLER
# ==============================
@bot.callback_query_handler(func=lambda call: True)
def process_callback(call):
    chat_id = call.message.chat.id
    action = call.data

    if chat_id not in user_data:
        bot.answer_callback_query(call.id, "❌ Send link again", show_alert=True)
        return

    url = user_data[chat_id]['url']

    if action == "opt3":
        markup = InlineKeyboardMarkup(row_width=2)
        markup.add(
            InlineKeyboardButton("720p", callback_data="res_720"),
            InlineKeyboardButton("480p", callback_data="res_480"),
            InlineKeyboardButton("360p", callback_data="res_360"),
        )
        bot.edit_message_text("Select quality:", chat_id, call.message.message_id, reply_markup=markup)
        return

    queue_size = task_queue.qsize()
    bot.edit_message_text(f"⏳ Added to queue. Position: {queue_size + 1}", chat_id, call.message.message_id)
    task_queue.put((chat_id, action, url, call.message.message_id))

# ==============================
# DOWNLOAD FUNCTION WITH RETRY
# ==============================
def download_with_retry(ydl_opts, url):
    for attempt in range(3):
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                return ydl.extract_info(url, download=True)
        except Exception:
            time.sleep(2)
    return None

def download_and_send(chat_id, action, url, msg_id):
    try:
        # DIRECT LINK
        if action == "opt6":
            ydl_opts = base_opts(chat_id, msg_id)
            ydl_opts['format'] = 'best'
            info = download_with_retry(ydl_opts, url)
            if info:
                direct = info.get("url")
                bot.send_message(chat_id, f"🔗 Direct Link:\n{direct}")
            else:
                bot.send_message(chat_id, "❌ Failed to fetch direct link!")
            return

        ydl_opts = base_opts(chat_id, msg_id)
        ydl_opts['outtmpl'] = f'temp_{chat_id}_%(title)s.%(ext)s'

        # FORMAT LOGIC
        if action == "opt1":
            ydl_opts['format'] = 'best[height<=720]'
        elif action == "opt2":
            ydl_opts['format'] = 'best[height<=720]'
            ydl_opts['writesubtitles'] = True
            ydl_opts['writeautomaticsub'] = True
            ydl_opts['subtitleslangs'] = ['bn']
        elif action.startswith("res_"):
            res = action.split("_")[1]
            ydl_opts['format'] = f'best[height<={res}]'
        elif action == "opt4":
            ydl_opts['format'] = 'bestaudio/best'
            ydl_opts['postprocessors'] = [
                {'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3'}
            ]
        elif action == "opt5":
            ydl_opts['noplaylist'] = False
            ydl_opts['format'] = 'best[ext=mp4]/best'

        bot.edit_message_text("⏳ Downloading...", chat_id, msg_id)
        info = download_with_retry(ydl_opts, url)

        if not info:
            bot.send_message(chat_id, "❌ Failed after retries!")
            return

        filename = yt_dlp.YoutubeDL(ydl_opts).prepare_filename(info)

        if action == "opt4":
            filename = filename.rsplit('.', 1)[0] + '.mp3'

        if os.path.getsize(filename) > 50 * 1024 * 1024:
            bot.send_message(chat_id, "❌ File too large! Use Direct Link.")
            os.remove(filename)
            return

        # SEND FILE
        with open(filename, 'rb') as f:
            if action == "opt4":
                bot.send_audio(chat_id, f)
            else:
                bot.send_video(chat_id, f)

        os.remove(filename)

    except yt_dlp.utils.DownloadError as e:
        err = str(e)
        if "Sign in to confirm" in err:
            bot.send_message(chat_id, "⚠️ YouTube blocked! Use Direct Link or try later.")
        else:
            bot.send_message(chat_id, f"❌ Error:\n{err[:100]}")

    except Exception as e:
        bot.send_message(chat_id, f"❌ Crash:\n{str(e)[:100]}")

# ==============================
print("🤖 Ultimate Downloader Bot is running...")
bot.infinity_polling()
