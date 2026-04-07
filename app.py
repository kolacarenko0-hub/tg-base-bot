import os
import time
import threading
import telebot
import re
from openai import OpenAI
from flask import Flask
from docx import Document

# --- 1. ВЕБ-СЕРВЕР ---
web_app = Flask(__name__)
@web_app.route('/')
def health_check(): return "Auto-Naming Docx Active", 200

def run_web():
    port = int(os.environ.get("PORT", 10000))
    web_app.run(host="0.0.0.0", port=port)

# --- 2. КОНФІГУРАЦІЯ ---
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
AI_KEY = os.environ.get("OPENAI_API_KEY")
bot = telebot.TeleBot(TOKEN)
client = OpenAI(api_key=AI_KEY)

user_sessions = {}
sessions_lock = threading.Lock()

# --- 3. ГЕНЕРАЦІЯ DOCX З АВТО-ВИЗНАЧЕННЯМ НАЗВИ ---
def create_auto_docx(chat_id):
    with sessions_lock:
        session = user_sessions.get(chat_id)
        if not session: return
        image_urls = session['urls']

    try:
        # Запит до AI: витягнути назву + повний звіт
        content = [
            {
                "type": "text", 
                "text": """Ти військовий технічний аналітик. 
                1. Визнач точну назву об'єкта на фото (якщо назв кілька, вибери основну).
                2. Склади детальний звіт.
                
                ФОРМАТ ВІДПОВІДІ:
                НАЗВА: [Тут тільки назва об'єкта]
                ЗВІТ:
                ### [НАЗВА ОБ'ЄКТА]
                ### ЗАГАЛЬНИЙ ОПИС
                ### ТТХ
                ### ОСОБЛИВОСТІ БУДОВИ
                ### ВИСНОВОК ТА БЕЗПЕКА
                
                Пиши професійно, витягуй всі цифри та маркування."""
            }
        ]
        
        for url in image_urls:
            content.append({"type": "image_url", "image_url": {"url": url}})

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": content}],
            max_tokens=3000,
            temperature=0
        )
        
        full_response = response.choices[0].message.content

        # Логіка розділення назви та тексту звіту
        try:
            name_part = full_response.split("ЗВІТ:")[0].replace("НАЗВА:", "").strip()
            report_part = full_response.split("ЗВІТ:")[1].strip()
        except:
            name_part = "Аналітичний_звіт"
            report_part = full_response

        # Створення документа
        doc = Document()
        doc.add_heading(name_part, 0)
        
        for line in report_part.split('\n'):
            if line.startswith('###'):
                doc.add_heading(line.replace('###', '').strip(), level=1)
            elif line.strip():
                doc.add_paragraph(line)

        # Очищення назви файлу для системи
        safe_name = re.sub(r'[^\w\s-]', '', name_part).strip().replace(' ', '_')
        if not safe_name: safe_name = "report"
        file_path = f"{safe_name}.docx"
        doc.save(file_path)

        with open(file_path, "rb") as f:
            bot.send_document(chat_id, f, caption=f"✅ Об'єкт визначено як: {name_part}")

        if os.path.exists(file_path): os.remove(file_path)

    except Exception as e:
        bot.send_message(chat_id, f"❌ Помилка: {e}")
    finally:
        with sessions_lock:
            user_sessions.pop(chat_id, None)

# --- 4. ОБРОБНИКИ ---
@bot.message_handler(content_types=['photo'])
def handle_photos(message):
    chat_id = message.chat.id
    file_info = bot.get_file(message.photo[-1].file_id)
    file_url = f"https://api.telegram.org/file/bot{TOKEN}/{file_info.file_path}"

    with sessions_lock:
        if chat_id not in user_sessions:
            user_sessions[chat_id] = {'urls': [], 'timer': None}
            bot.send_message(chat_id, "🔍 Аналізую зображення та визначаю модель...")
            bot.send_chat_action(chat_id, 'typing')
        
        user_sessions[chat_id]['urls'].append(file_url)
        
        if user_sessions[chat_id]['timer']:
            user_sessions[chat_id]['timer'].cancel()
        
        # Чекаємо 8 секунд, щоб зібрати всі фото альбому
        t = threading.Timer(8.0, create_auto_docx, args=[chat_id])
        user_sessions[chat_id]['timer'] = t
        t.start()

# --- 5. ЗАПУСК ---
if __name__ == "__main__":
    threading.Thread(target=run_web, daemon=True).start()
    bot.remove_webhook()
    time.sleep(1)
    bot.get_updates(offset=-1, timeout=1)
    print("Бот з авто-визначенням назви запущений!")
    bot.infinity_polling(timeout=90)
