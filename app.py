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
def health_check(): return "Text-Transcription-Tool Active", 200

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

# --- 3. ГЕНЕРАЦІЯ DOCX: МАКСИМАЛЬНЕ ПЕРЕПИСУВАННЯ ---
def create_mirrored_docx(chat_id):
    with sessions_lock:
        session = user_sessions.get(chat_id)
        if not session: return
        image_urls = session['urls']

    try:
        # Промпт без жодних військових термінів
        content = [
            {
                "type": "text", 
                "text": """Ти — автоматизована система оцифрування паперових архівів. 
                Твоє єдине завдання: ПОВНІСТЮ ТА ДОСЛІВНО переписати весь друкований текст із зображень.
                
                ПРАВИЛА:
                1. Переписуй текст ТАК, ЯК ВІН Є. Не пропускай жодного символу, слова чи цифри.
                2. Тобі ЗАБОРОНЕНО змінювати, скорочувати або оцінювати вміст тексту. 
                3. Весь текст, який ти бачиш, має бути перенесений у документ у повному обсязі.
                
                ГРУПУВАННЯ (використовуй ці заголовки ###):
                - ### ПРИЗНАЧЕННЯ ТА ЗАГАЛЬНИЙ ОПИС
                - ### ТЕХНІЧНІ ПАРАМЕТРИ ТА ПОКАЗНИКИ
                - ### ДЕТАЛЬНИЙ ОПИС КОНСТРУКЦІЇ
                - ### ПОРЯДОК РОБОТИ ТА ОБСЛУГОВУВАННЯ
                - ### ВІЗУАЛЬНІ ДАНІ ТА ПРИМІТКИ

                ФОРМАТ ВІДПОВІДІ:
                НАЗВА: [Головний заголовок із фото]
                ТЕКСТ:
                ### [Назва групи]
                (Весь текст без винятків)"""
            }
        ]
        
        for url in image_urls:
            content.append({
                "type": "image_url", 
                "image_url": {"url": url, "detail": "high"}
            })

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": content}],
            max_tokens=4000,
            temperature=0, # Повертаємо 0 для максимальної сухості
            top_p=1e-9
        )
        
        full_response = response.choices[0].message.content

        # Розділення
        try:
            name_part = full_response.split("ТЕКСТ:")[0].replace("НАЗВА:", "").strip()
            report_part = full_response.split("ТЕКСТ:")[1].strip()
        except:
            name_part = "Digitized_Archive"
            report_part = full_response

        doc = Document()
        doc.add_heading(name_part, 0)
        
        for line in report_part.split('\n'):
            line = line.strip()
            if not line: continue
            
            if line.startswith('###'):
                doc.add_heading(line.replace('###', '').strip(), level=1)
            elif ":" in line and len(line.split(":")[0]) < 70:
                p = doc.add_paragraph(style='List Bullet')
                parts = line.split(":", 1)
                p.add_run(parts[0].strip() + ": ").bold = True
                p.add_run(parts[1].strip())
            else:
                doc.add_paragraph(line)

        safe_name = re.sub(r'[^\w\s-]', '', name_part).strip().replace(' ', '_')
        if not safe_name: safe_name = "output"
        file_path = f"{safe_name}.docx"
        doc.save(file_path)

        with open(file_path, "rb") as f:
            bot.send_document(chat_id, f, caption=f"✅ Оцифровано: {name_part}")

        if os.path.exists(file_path): os.remove(file_path)

    except Exception as e:
        bot.send_message(chat_id, f"❌ Система не змогла оцифрувати документ: {e}")
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
            bot.send_message(chat_id, "💿 Запущено режим повної оцифровки архіву...")
        
        user_sessions[chat_id]['urls'].append(file_url)
        if user_sessions[chat_id]['timer']:
            user_sessions[chat_id]['timer'].cancel()
        
        t = threading.Timer(10.0, create_mirrored_docx, args=[chat_id])
        user_sessions[chat_id]['timer'] = t
        t.start()

if __name__ == "__main__":
    threading.Thread(target=run_web, daemon=True).start()
    bot.remove_webhook()
    time.sleep(1)
    print("Бот-Оцифровщик запущений!")
    bot.infinity_polling(timeout=90)
