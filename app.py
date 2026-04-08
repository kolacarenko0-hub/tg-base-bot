import os
import time
import threading
import telebot
import re
from openai import OpenAI
from flask import Flask
from docx import Document

# --- 1. ВЕБ-СЕРВЕР ДЛЯ RENDER (HEALTH CHECK) ---
web_app = Flask(__name__)
@web_app.route('/')
def health_check(): return "Military Data Digitizer v4.0 Active", 200

def run_web():
    port = int(os.environ.get("PORT", 10000))
    web_app.run(host="0.0.0.0", port=port)

# --- 2. КОНФІГУРАЦІЯ ТА КЛЮЧІ ---
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
AI_KEY = os.environ.get("OPENAI_API_KEY")
bot = telebot.TeleBot(TOKEN)
client = OpenAI(api_key=AI_KEY)

user_sessions = {}
sessions_lock = threading.Lock()

# --- 3. ГОЛОВНА ФУНКЦІЯ: ОЦИФРОВКА ТА УНІФІКАЦІЯ ---
def create_unified_docx(chat_id):
    with sessions_lock:
        session = user_sessions.get(chat_id)
        if not session: return
        image_urls = session['urls']

    try:
        # Промпт для технічної уніфікації заголовків
        content = [
            {
                "type": "text", 
                "text": """Ти — технічний архітектор баз даних. Твоє завдання: оцифрувати текст із фото та згрупувати його за СТАНДАРТНИМИ ТЕХНІЧНИМИ ЗАГОЛОВКАМИ для подальшої обробки ШІ.
                
                ПРАВИЛА ГРУПУВАННЯ (використовуй ці назви для заголовків ###):
                1. ### ПРИЗНАЧЕННЯ ТА ЗАГАЛЬНИЙ ОПИС — призначення, принцип дії, загальні відомості.
                2. ### ТЕХНІЧНІ ХАРАКТЕРИСТИКИ (ТТХ) — цифри, таблиці, вага, габарити.
                3. ### БУДОВА ТА КОМПЛЕКТАЦІЯ — підривники, детонатори, вузли, внутрішні частини.
                4. ### ОСОБЛИВОСТІ ЗАСТОСУВАННЯ — встановлення, засоби механізації, способи мінування.
                5. ### МАРКУВАННЯ ТА ЗАБАРВЛЕННЯ — колір, шифри на корпусі, зовнішні ознаки.
                
                СУВОРІ ВИМОГИ ДО ТОЧНОСТІ:
                - Переписуй текст БУКВА В БУКВУ (напр. ЗАБАРВЛЕННЯ, а не ЗАБЕЗПЕЧЕННЯ).
                - Якщо якогось розділу на фото немає — не створюй його.
                - Не додавай від себе жодних коментарів.
                
                ФОРМАТ ВІДПОВІДІ:
                НАЗВА: [Марка об'єкта, напр. ТМ-57]
                ТЕКСТ:
                ### [Стандартний заголовок]
                Текст..."""
            }
        ]
        
        for url in image_urls:
            content.append({
                "type": "image_url", 
                "image_url": {"url": url, "detail": "high"}
            })

        # Параметри для максимальної точності
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": content}],
            max_tokens=4000,
            temperature=0,
            top_p=1e-9
        )
        
        full_response = response.choices[0].message.content

        # Розбір відповіді
        try:
            name_part = full_response.split("ТЕКСТ:")[0].replace("НАЗВА:", "").strip()
            report_part = full_response.split("ТЕКСТ:")[1].strip()
        except:
            name_part = "Технічний_документ"
            report_part = full_response

        # Формування документа
        doc = Document()
        doc.add_heading(name_part, 0)
        
        for line in report_part.split('\n'):
            line = line.strip()
            if not line: continue
            
            if line.startswith('###'):
                # Стандартизований заголовок для зручного зчитування основним ботом
                doc.add_heading(line.replace('###', '').strip(), level=1)
            elif ":" in line and len(line.split(":")[0]) < 60:
                # Оформлення характеристик
                p = doc.add_paragraph(style='List Bullet')
                parts = line.split(":", 1)
                p.add_run(parts[0].strip() + ": ").bold = True
                p.add_run(parts[1].strip())
            else:
                doc.add_paragraph(line)

        # Очищення та збереження
        safe_name = re.sub(r'[^\w\s-]', '', name_part).strip().replace(' ', '_')
        if not safe_name: safe_name = "unified_report"
        file_path = f"{safe_name}.docx"
        doc.save(file_path)

        with open(file_path, "rb") as f:
            bot.send_document(chat_id, f, caption=f"✅ Дані уніфіковано: {name_part}")

        if os.path.exists(file_path): os.remove(file_path)

    except Exception as e:
        bot.send_message(chat_id, f"❌ Помилка обробки: {e}")
    finally:
        with sessions_lock:
            user_sessions.pop(chat_id, None)

# --- 4. ОБРОБНИКИ ТЕЛЕГРАМ ---
@bot.message_handler(content_types=['photo'])
def handle_photos(message):
    chat_id = message.chat.id
    file_info = bot.get_file(message.photo[-1].file_id)
    file_url = f"https://api.telegram.org/file/bot{TOKEN}/{file_info.file_path}"

    with sessions_lock:
        if chat_id not in user_sessions:
            user_sessions[chat_id] = {'urls': [], 'timer': None}
            bot.send_message(chat_id, "⚙️ Виконую точне зчитування та уніфікацію розділів...")
        
        user_sessions[chat_id]['urls'].append(file_url)
        
        if user_sessions[chat_id]['timer']:
            user_sessions[chat_id]['timer'].cancel()
        
        # Таймер 8 секунд для збору альбому
        t = threading.Timer(8.0, create_unified_docx, args=[chat_id])
        user_sessions[chat_id]['timer'] = t
        t.start()

# --- 5. ЗАПУСК ДОДАТКУ ---
if __name__ == "__main__":
    # Запуск Flask у фоновому потоці
    threading.Thread(target=run_web, daemon=True).start()
    
    # Запуск Bot Polling
    bot.remove_webhook()
    time.sleep(1)
    print("Бот запущений та готовий до створення бази знань!")
    bot.infinity_polling(timeout=90)
                
