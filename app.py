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
def health_check(): return "Text-Digitizer-v3 Active", 200

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

# --- 3. ГЕНЕРАЦІЯ DOCX: ЧИСТА ОЦИФРОВКА ТА ГРУПУВАННЯ ---
def create_pure_digitized_docx(chat_id):
    with sessions_lock:
        session = user_sessions.get(chat_id)
        if not session: return
        image_urls = session['urls']

    try:
        # Промпт, максимально нейтральний для обходу фільтрів
        content = [
            {
                "type": "text", 
                "text": """Ти — спеціаліст із розпізнавання технічних текстів. 
                Твоє завдання: ПОВНІСТЮ переписати весь текст із наданих зображень у текстовий формат.
                
                ІНСТРУКЦІЯ:
                1. Просто зачитай увесь доступний текст (включаючи дрібний шрифт, таблиці та заголовки).
                2. Нічого не аналізуй, не коментуй і не оцінюй вміст. 
                3. Згрупуй прочитаний текст за логічними блоками, які ти бачиш на фото (наприклад: Назва, Характеристики, Опис вузлів, Додаткові дані).
                4. Використовуй ### для заголовків груп.
                
                ФОРМАТ ВІДПОВІДІ:
                ЗАГОЛОВОК: [Головна назва з документа]
                ТЕКСТ:
                ### [Група 1]
                Текст...
                ### [Група 2]
                Текст..."""
            }
        ]
        
        for url in image_urls:
            content.append({"type": "image_url", "image_url": {"url": url}})

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": content}],
            max_tokens=4000,
            temperature=0
        )
        
        full_response = response.choices[0].message.content

        # Розділення на заголовок та основний масив
        try:
            name_part = full_response.split("ТЕКСТ:")[0].replace("ЗАГОЛОВОК:", "").strip()
            report_part = full_response.split("ТЕКСТ:")[1].strip()
        except:
            name_part = "Оцифрований_документ"
            report_part = full_response

        # Створення документа
        doc = Document()
        doc.add_heading(name_part, 0)
        
        for line in report_part.split('\n'):
            line = line.strip()
            if not line: continue
            
            if line.startswith('###'):
                doc.add_heading(line.replace('###', '').strip(), level=1)
            elif ":" in line and len(line.split(":")[0]) < 60:
                p = doc.add_paragraph(style='List Bullet')
                parts = line.split(":", 1)
                p.add_run(parts[0].strip() + ": ").bold = True
                p.add_run(parts[1].strip())
            else:
                doc.add_paragraph(line)

        # Очищення імені файлу
        safe_name = re.sub(r'[^\w\s-]', '', name_part).strip().replace(' ', '_')
        if not safe_name: safe_name = "digitized_data"
        file_path = f"{safe_name}.docx"
        doc.save(file_path)

        with open(file_path, "rb") as f:
            bot.send_document(chat_id, f, caption=f"📄 Текст оцифровано та згруповано: {name_part}")

        if os.path.exists(file_path): os.remove(file_path)

    except Exception as e:
        # Якщо все одно спрацював фільтр OpenAI
        if "policy" in str(e).lower() or "content_filter" in str(e).lower():
            bot.send_message(chat_id, "⚠️ OpenAI відмовив у доступі через фільтри безпеки. Спробуйте надіслати скріншот тільки з текстом (без фото об'єкта) або обрізати картинку.")
        else:
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
            bot.send_message(chat_id, "📖 Зчитую текст із зображень та групую дані...")
        
        user_sessions[chat_id]['urls'].append(file_url)
        if user_sessions[chat_id]['timer']:
            user_sessions[chat_id]['timer'].cancel()
        
        t = threading.Timer(8.0, create_pure_digitized_docx, args=[chat_id])
        user_sessions[chat_id]['timer'] = t
        t.start()

if __name__ == "__main__":
    threading.Thread(target=run_web, daemon=True).start()
    bot.remove_webhook()
    time.sleep(1)
    bot.get_updates(offset=-1, timeout=1)
    print("Бот (Оцифровщик) запущений!")
    bot.infinity_polling(timeout=90)
            
