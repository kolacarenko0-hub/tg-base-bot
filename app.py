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
def health_check(): return "Full-Data-Extractor Active", 200

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

# --- 3. ГЕНЕРАЦІЯ DOCX: МАКСИМАЛЬНА ЕКСТРАКЦІЯ ---
def create_full_data_docx(chat_id):
    with sessions_lock:
        session = user_sessions.get(chat_id)
        if not session: return
        image_urls = session['urls']

    try:
        # Промпт, що вимагає 100% перенесення тексту
        content = [
            {
                "type": "text", 
                "text": """Ти — технічний копіїст. Твоє завдання: ПОВНІСТЮ ТА ДОСЛІВНО перенести весь текст із зображень у документ. 
                Нічого не скорочуй! Якщо в оригіналі 10 речень — у тебе має бути 10 речень.
                
                ІНСТРУКЦІЇ:
                1. Знайди та витягни КОЖНЕ слово, кожну цифру, кожну виноску та примітку.
                2. Текст має бути МАКСИМАЛЬНО ОБ'ЄМНИМ. Якщо бачиш опис — копіюй його повністю.
                3. Особлива увага на специфічні назви (детонатори, підривники, індекси) — не смій їх пропускати.
                4. Обов'язково описуй те, що бачиш на малюнках та схемах текстом.
                
                РОЗПОДІЛИ ВЕСЬ ВИТЯГНУТИЙ ТЕКСТ ЗА ЦИМИ ЗАГОЛОВКАМИ (###):
                - ПРИЗНАЧЕННЯ ТА ПРИНЦИП ДІЇ (Весь вступний та описовий текст).
                - ТЕХНІЧНІ ХАРАКТЕРИСТИКИ (ТТХ) (Всі дані з таблиць та цифри).
                - ДЕТАЛЬНИЙ ОПИС БУДОВИ (Вузи, підривники, матеріали).
                - ПОРЯДОК ЗАСТОСУВАННЯ ТА МЕХАНІЗАЦІЯ (Методи встановлення).
                - ВІЗУАЛЬНІ ОЗНАКИ, МАРКУВАННЯ ТА БЕЗПЕКА (Колір, написи).

                ФОРМАТ ВІДПОВІДІ:
                НАЗВА: [Марка об'єкта]
                ТЕКСТ:
                ### [Стандартний заголовок]
                (Сюди пиши весь об'єм тексту без скорочень)"""
            }
        ]
        
        for url in image_urls:
            content.append({
                "type": "image_url", 
                "image_url": {"url": url, "detail": "high"}
            })

        # Трохи підняли температуру (0.1), щоб він краще зв'язував довгі тексти
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": content}],
            max_tokens=4000,
            temperature=0.1
        )
        
        full_response = response.choices[0].message.content

        try:
            name_part = full_response.split("ТЕКСТ:")[0].replace("НАЗВА:", "").strip()
            report_part = full_response.split("ТЕКСТ:")[1].strip()
        except:
            name_part = "Повний_технічний_звіт"
            report_part = full_response

        # Створення документа
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
        if not safe_name: safe_name = "full_data_report"
        file_path = f"{safe_name}.docx"
        doc.save(file_path)

        with open(file_path, "rb") as f:
            bot.send_document(chat_id, f, caption=f"📄 Дані оцифровано в повному обсязі: {name_part}")

        if os.path.exists(file_path): os.remove(file_path)

    except Exception as e:
        bot.send_message(chat_id, f"❌ Помилка екстракції: {e}")
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
            bot.send_message(chat_id, "🚀 Запущено повну екстракцію даних без скорочень...")
        
        user_sessions[chat_id]['urls'].append(file_url)
        if user_sessions[chat_id]['timer']:
            user_sessions[chat_id]['timer'].cancel()
        
        # Збільшили час до 10 сек, щоб точно зібрати альбом
        t = threading.Timer(10.0, create_full_data_docx, args=[chat_id])
        user_sessions[chat_id]['timer'] = t
        t.start()

if __name__ == "__main__":
    threading.Thread(target=run_web, daemon=True).start()
    bot.remove_webhook()
    time.sleep(1)
    print("Бот (Повна Екстракція) запущений!")
    bot.infinity_polling(timeout=90)
