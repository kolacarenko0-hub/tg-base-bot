import os
import time
import threading
import base64
import telebot
from openai import OpenAI
from flask import Flask

# --- 1. СЕРВЕР ---
web_app = Flask(__name__)
@web_app.route('/')
def health_check(): return "Vision Scanner Active", 200

def run_web():
    port = int(os.environ.get("PORT", 10000))
    web_app.run(host="0.0.0.0", port=port)

# --- 2. КОНФІГУРАЦІЯ ---
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
AI_KEY = os.environ.get("OPENAI_API_KEY")
bot = telebot.TeleBot(TOKEN)
client = OpenAI(api_key=AI_KEY)

# Тимчасове сховище для альбомів
user_sessions = {}
sessions_lock = threading.Lock()

# --- 3. ФУНКЦІЯ АНАЛІЗУ ЗОБРАЖЕНЬ (GPT-4o-mini Vision) ---
def analyze_images(chat_id):
    with sessions_lock:
        session = user_sessions.get(chat_id)
        if not session: return
        image_urls = session['urls']
        caption = session['caption'] if session['caption'] else "Об'єкт без назви"

    try:
        # Формуємо запит з кількома зображеннями
        content = [
            {
                "type": "text", 
                "text": f"Ти військовий технічний аналітик. Оцифруй дані з цих фото про: {caption}. "
                        "Зроби чіткий звіт: ### НАЗВА, ### ЗАГАЛЬНЕ, ### ТТХ (формат Параметр — Значення), ### ДОДАТКОВО. "
                        "Якщо на різних фото одна і та ж міна — об'єднай дані."
            }
        ]
        
        for url in image_urls:
            content.append({
                "type": "image_url",
                "image_url": {"url": url}
            })

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": content}],
            max_tokens=2000
        )

        final_text = response.choices[0].message.content
        bot.send_message(chat_id, final_text, parse_mode="Markdown")

    except Exception as e:
        bot.send_message(chat_id, f"❌ Помилка аналізу: {e}")
    finally:
        with sessions_lock:
            user_sessions.pop(chat_id, None)

# --- 4. ОБРОБНИКИ ---

@bot.message_handler(content_types=['photo'])
def handle_photos(message):
    chat_id = message.chat.id
    
    # Отримуємо пряме посилання на фото з серверів Telegram
    file_info = bot.get_file(message.photo[-1].file_id)
    file_url = f"https://api.telegram.org/file/bot{TOKEN}/{file_info.file_path}"

    with sessions_lock:
        if chat_id not in user_sessions:
            user_sessions[chat_id] = {'urls': [], 'caption': message.caption, 'timer': None}
            bot.send_chat_action(chat_id, 'typing')
        
        user_sessions[chat_id]['urls'].append(file_url)
        
        # Скидаємо таймер (чекаємо 6 секунд доки долетять всі фото альбому)
        if user_sessions[chat_id]['timer']:
            user_sessions[chat_id]['timer'].cancel()
        
        t = threading.Timer(6.0, analyze_images, args=[chat_id])
        user_sessions[chat_id]['timer'] = t
        t.start()

# --- 5. ЗАПУСК ---
if __name__ == "__main__":
    threading.Thread(target=run_web, daemon=True).start()
    
    # Очищення старих сесій для уникнення 409
    bot.remove_webhook()
    time.sleep(1)
    bot.get_updates(offset=-1, timeout=1)
    
    print("Бот на базі Vision AI запущений!")
    bot.infinity_polling(timeout=90)
        
