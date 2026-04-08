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
def health_check(): return "Precision-OCR Active", 200

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

# --- 3. ГЕНЕРАЦІЯ DOCX З ПІДВИЩЕНОЮ ТОЧНІСТЮ ---
def create_high_precision_docx(chat_id):
    with sessions_lock:
        session = user_sessions.get(chat_id)
        if not session: return
        image_urls = session['urls']

    try:
        # Промпт для посимвольної точності
        content = [
            {
                "type": "text", 
                "text": """Ти — надточний інструмент оптичного розпізнавання символів (OCR). 
                Твоє завдання: ПЕРЕПИСАТИ текст із фото буква в букву.
                
                СУВОРІ ПРАВИЛА:
                1. НЕ ВГАДУЙ СЛОВА за змістом. Дивись на кожен символ окремо. 
                   Приклад: якщо написано 'ЗАБАРВЛЕННЯ', не смій писати 'ЗАБЕЗПЕЧЕННЯ'.
                2. Переписуй текст точно так, як він надрукований (регістр, скорочення, тире).
                3. Згрупуй отриманий текст за логічними блоками (заголовки, таблиці, пункти).
                4. Витягни абсолютно всі цифри, індекси та маркування.

                ФОРМАТ ВІДПОВІДІ:
                ЗАГОЛОВОК: [Головний напис]
                ТЕКСТ:
                ### [Група]
                Текст..."""
            }
        ]
        
        for url in image_urls:
            content.append({
                "type": "image_url", 
                "image_url": {
                    "url": url,
                    "detail": "high"  # ПРИМУСОВИЙ ВИСОКИЙ РІВЕНЬ ДЕТАЛІЗАЦІЇ
                }
            })

        # Використовуємо Temperature=0 для нульової креативності
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": content}],
            max_tokens=4000,
            temperature=0,
            top_p=1e-9
        )
        
        full_response = response.choices[0].message.content

        # Розділення
        try:
            name_part = full_response.split("ТЕКСТ:")[0].replace("ЗАГОЛОВОК:", "").strip()
            report_part = full_response.split("ТЕКСТ:")[1].strip()
        except:
            name_part = "Precision_Report"
            report_part = full_response

        # Створення DOCX
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

        safe_name = re.sub(r'[^\w\s-]', '', name_part).strip().replace(' ', '_')
        if not safe_name: safe_name = "report_precision"
        file_path = f"{safe_name}.docx"
        doc.save(file_path)

        with open(file_path, "rb") as f:
            bot.send_document(chat_id, f, caption=f"📄 Текст оцифровано з високою точністю: {name_part}")

        if os.path.exists(file_path): os.remove(file_path)

    except Exception as e:
        bot.send_message(chat_id, f"❌ Помилка точності: {e}")
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
            bot.send_message(chat_id, "🔍 Активував режим максимальної точності зчитування...")
        
        user_sessions[chat_id]['urls'].append(file_url)
        if user_sessions[chat_id]['timer']:
            user_sessions[chat_id]['timer'].cancel()
        
        t = threading.Timer(8.0, create_high_precision_docx, args=[chat_id])
        user_sessions[chat_id]['timer'] = t
        t.start()

if __name__ == "__main__":
    threading.Thread(target=run_web, daemon=True).start()
    bot.remove_webhook()
    time.sleep(1)
    bot.get_updates(offset=-1, timeout=1)
    print("Бот (Precision Mode) запущений!")
    bot.infinity_polling(timeout=90)
                
