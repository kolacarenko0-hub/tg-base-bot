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
def health_check(): return "Total Digitizer Active", 200

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

# --- 3. ГЕНЕРАЦІЯ DOCX: ПОВНЕ ГРУПУВАННЯ ТЕКСТУ ---
def create_total_docx(chat_id):
    with sessions_lock:
        session = user_sessions.get(chat_id)
        if not session: return
        image_urls = session['urls']

    try:
        # Промпт для повної оцифровки без втрат
        content = [
            {
                "type": "text", 
                "text": """Ти — професійний стенографіст та технічний аналітик. 
                Твоє завдання: ПОВНІСТЮ перенести весь текст із зображень у документ.
                
                ІНСТРУКЦІЯ:
                1. Витягни абсолютно всі написи, включаючи дрібний шрифт, примітки та дані в таблицях.
                2. Згрупуй цей текст за логічними розділами. 
                3. Якщо назва розділу написана капсом або жирним — збережи це виділення.
                4. Не пропускай жодної абревіатури, індексу чи цифрового показника.
                
                СТРУКТУРА ВІДПОВІДІ:
                НАЗВА: [Точна назва об'єкта з фото]
                ЗВІТ:
                [Тут має бути весь структурований текст, розбитий на логічні блоки за допомогою заголовків ###]
                """
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

        # Розділення назви та тексту
        try:
            name_part = full_response.split("ЗВІТ:")[0].replace("НАЗВА:", "").strip()
            report_part = full_response.split("ЗВІТ:")[1].strip()
        except:
            name_part = "Повний_текстовий_звіт"
            report_part = full_response

        # Створення DOCX
        doc = Document()
        doc.add_heading(name_part, 0)
        
        for line in report_part.split('\n'):
            line = line.strip()
            if not line: continue
            
            if line.startswith('###'):
                # Створюємо новий розділ
                doc.add_heading(line.replace('###', '').strip(), level=1)
            elif ":" in line and len(line.split(":")[0]) < 60:
                # Форматуємо пари "Ключ: Значення"
                p = doc.add_paragraph(style='List Bullet')
                parts = line.split(":", 1)
                p.add_run(parts[0].strip() + ": ").bold = True
                p.add_run(parts[1].strip())
            else:
                # Звичайний текст
                doc.add_paragraph(line)

        # Збереження файлу
        safe_name = re.sub(r'[^\w\s-]', '', name_part).strip().replace(' ', '_')
        if not safe_name: safe_name = "full_report"
        file_path = f"{safe_name}.docx"
        doc.save(file_path)

        with open(file_path, "rb") as f:
            bot.send_document(chat_id, f, caption=f"📄 Повна оцифровка тексту виконана: {name_part}")

        if os.path.exists(file_path): os.remove(file_path)

    except Exception as e:
        bot.send_message(chat_id, f"❌ Помилка оцифровки: {e}")
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
            bot.send_message(chat_id, "📑 Починаю повне зчитування та групування тексту...")
        
        user_sessions[chat_id]['urls'].append(file_url)
        if user_sessions[chat_id]['timer']:
            user_sessions[chat_id]['timer'].cancel()
        
        # 8 секунд на збір усіх фото в один звіт
        t = threading.Timer(8.0, create_total_docx, args=[chat_id])
        user_sessions[chat_id]['timer'] = t
        t.start()

if __name__ == "__main__":
    threading.Thread(target=run_web, daemon=True).start()
    bot.remove_webhook()
    time.sleep(1)
    bot.get_updates(offset=-1, timeout=1)
    print("Бот (Повна оцифровка) запущений!")
    bot.infinity_polling(timeout=90)
            
