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
def health_check(): return "Structure-OCR-Final Active", 200

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

# --- 3. ГЕНЕРАЦІЯ DOCX: СТРУКТУРОВАНЕ ПЕРЕПИСУВАННЯ ---
def create_final_structured_docx(chat_id):
    with sessions_lock:
        session = user_sessions.get(chat_id)
        if not session: return
        image_urls = session['urls']

    try:
        content = [
            {
                "type": "text", 
                "text": """Ти — автоматизована система оцифрування технічних текстів. 
                Твоє завдання: ПОВНІСТЮ переписати весь текст із зображень, суворо дотримуючись структури з ###.
                
                ВИМОГИ ДО ФОРМАТУ:
                1. Кожну логічну групу тексту обов'язково починай із заголовка, перед яким стоять ТРИ РЕШІТКИ (###).
                2. Переписуй текст дослівно, без скорочень.
                3. Не додавай нічого від себе.
                
                ОБОВ'ЯЗКОВІ ГРУПИ (якщо дані присутні):
                ### ПРИЗНАЧЕННЯ ТА ЗАГАЛЬНИЙ ОПИС
                ### ТЕХНІЧНІ ПАРАМЕТРИ ТА ПОКАЗНИКИ
                ### ДЕТАЛЬНИЙ ОПИС КОНСТРУКЦІЇ
                ### ПОРЯДОК РОБОТИ ТА ОБСЛУГОВУВАННЯ
                ### ВІЗУАЛЬНІ ДАНІ ТА ПРИМІТКИ

                ФОРМАТ ВІДПОВІДІ:
                НАЗВА: [Назва з документа]
                ТЕКСТ:
                ### ПРИЗНАЧЕННЯ ТА ЗАГАЛЬНИЙ ОПИС
                (Текст тут...)
                ### ТЕХНІЧНІ ПАРАМЕТРИ ТА ПОКАЗНИКИ
                (Текст тут...)"""
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
            temperature=0
        )
        
        full_response = response.choices[0].message.content

        try:
            name_part = full_response.split("ТЕКСТ:")[0].replace("НАЗВА:", "").strip()
            report_part = full_response.split("ТЕКСТ:")[1].strip()
        except:
            name_part = "Technical_Document"
            report_part = full_response

        # Створення документа
        doc = Document()
        doc.add_heading(name_part, 0)
        
        # Розбиваємо текст по символу ###
        sections = re.split(r'(### .+\n)', report_part)
        
        current_section_title = ""
        for part in sections:
            part = part.strip()
            if not part: continue
            
            if part.startswith('###'):
                current_section_title = part.replace('###', '').strip()
                doc.add_heading(current_section_title, level=1)
            else:
                # Обробка основного тексту всередині секції
                for line in part.split('\n'):
                    line = line.strip()
                    if not line: continue
                    if ":" in line and len(line.split(":")[0]) < 60:
                        p = doc.add_paragraph(style='List Bullet')
                        key_val = line.split(":", 1)
                        p.add_run(key_val[0].strip() + ": ").bold = True
                        p.add_run(key_val[1].strip())
                    else:
                        doc.add_paragraph(line)

        safe_name = re.sub(r'[^\w\s-]', '', name_part).strip().replace(' ', '_')
        if not safe_name: safe_name = "document"
        file_path = f"{safe_name}.docx"
        doc.save(file_path)

        with open(file_path, "rb") as f:
            bot.send_document(chat_id, f, caption=f"✅ Документ структуровано через ###: {name_part}")

        if os.path.exists(file_path): os.remove(file_path)

    except Exception as e:
        bot.send_message(chat_id, f"❌ Помилка структурування: {e}")
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
            bot.send_message(chat_id, "📑 Оцифровую дані з використанням ### маркування...")
        
        user_sessions[chat_id]['urls'].append(file_url)
        if user_sessions[chat_id]['timer']:
            user_sessions[chat_id]['timer'].cancel()
        
        t = threading.Timer(10.0, create_final_structured_docx, args=[chat_id])
        user_sessions[chat_id]['timer'] = t
        t.start()

if __name__ == "__main__":
    threading.Thread(target=run_web, daemon=True).start()
    bot.remove_webhook()
    time.sleep(1)
    print("Бот готовий. Формат заголовків: ###")
    bot.infinity_polling(timeout=90)
