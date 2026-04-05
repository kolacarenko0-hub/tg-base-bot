import os
import time
import threading
import telebot
import fitz  # PyMuPDF
import docx
from openai import OpenAI
from io import BytesIO
from flask import Flask

# --- 1. ВЕБ-СЕРВЕР ДЛЯ HEALTH CHECK ---
web_app = Flask(__name__)

@web_app.route('/')
def health_check():
    return "Bot is active!", 200

def run_web():
    port = int(os.environ.get("PORT", 10000))
    web_app.run(host="0.0.0.0", port=port)

# --- 2. НАЛАШТУВАННЯ ---
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
AI_KEY = os.environ.get("OPENAI_API_KEY")

if not TOKEN or not AI_KEY:
    print("❌ Помилка: Ключі TELEGRAM_BOT_TOKEN або OPENAI_API_KEY не знайдено!")
    exit(1)

bot = telebot.TeleBot(TOKEN)
client = OpenAI(api_key=AI_KEY)

# --- 3. ФУНКЦІЇ ОБРОБКИ ТЕКСТУ ---
def extract_text(file_path, extension):
    text = ""
    try:
        if extension == 'pdf':
            with fitz.open(file_path) as doc:
                text = "".join([page.get_text() for page in doc])
        elif extension == 'docx':
            doc = docx.Document(file_path)
            text = "\n".join([para.text for para in doc.paragraphs])
    except Exception as e:
        print(f"Помилка зчитування файлу: {e}")
    return text

def process_with_ai(chat_id, initial_status_id, raw_text):
    all_results = []
    step = 4000  # Розмір частини тексту
    chunks = [raw_text[i:i+step] for i in range(0, len(raw_text), step)]
    total = len(chunks)
    
    current_status_id = initial_status_id

    for idx, chunk in enumerate(chunks, 1):
        progress = int((idx / total) * 100)
        
        # Створюємо нове повідомлення про статус для підтримки активності сесії
        status_text = (
            f"⏳ **Аналіз бази знань...**\n"
            f"Прогрес: {progress}% [{idx}/{total}]\n\n"
            f"⚠️ *Бот працює, не закривайте чат. Це створює активність для сервера.*"
        )
        
        try:
            # Видаляємо старе повідомлення
            bot.delete_message(chat_id, current_status_id)
        except:
            pass

        try:
            # Надсилаємо нове (новий HTTP-запит тримає Render в тонусі)
            new_msg = bot.send_message(chat_id, status_text, parse_mode="Markdown")
            current_status_id = new_msg.message_id
        except Exception as e:
            print(f"Помилка оновлення статусу: {e}")

        # Запит до OpenAI
        try:
            res = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": f"Ти техредактор. Сформуй базу знань. Формули в LaTeX. Текст: {chunk}"}],
                temperature=0.2
            )
            all_results.append(res.choices[0].message.content)
        except Exception as e:
            print(f"OpenAI Error на частині {idx}: {e}")
            all_results.append(f"\n[Помилка обробки частини {idx}]\n")
            
        # Пауза для стабільності
        time.sleep(1.5)
            
    return "\n\n".join(all_results), current_status_id

# --- 4. ОБРОБНИКИ ТЕЛЕГРАМ ---
@bot.message_handler(commands=['start'])
def welcome(message):
    bot.reply_to(message, "🫡 Бот активний! Надсилайте файл PDF або DOCX для створення бази знань.")

@bot.message_handler(content_types=['document'])
def handle_file(message):
    file_name = message.document.file_name
    ext = file_name.split('.')[-1].lower()
    temp_path = f"process_{message.chat.id}.tmp"
    
    if ext not in ['pdf', 'docx']:
        bot.reply_to(message, "❌ Формат не підтримується. Тільки PDF або DOCX.")
        return

    status = bot.reply_to(message, "📥 Починаю завантаження та зчитування...")
    
    try:
        # Завантаження файлу
        file_info = bot.get_file(message.document.file_id)
        downloaded = bot.download_file(file_info.file_path)
        with open(temp_path, "wb") as f:
            f.write(downloaded)

        text = extract_text(temp_path, ext)
        if not text.strip():
            bot.edit_message_text("❌ Файл порожній або не зчитується.", message.chat.id, status.message_id)
            return

        # Запуск тривалої обробки з "мережевим диханням"
        result_text, final_status_id = process_with_ai(message.chat.id, status.message_id, text)

        # Формування фінального файлу
        out = BytesIO()
        out.name = "base_knowledge.txt"
        out.write(result_text.encode('utf-8'))
        out.seek(0)

        bot.send_document(message.chat.id, out, caption=f"✅ Базу знань сформовано!\nФайл: {file_name}")
        
        # Видаляємо останній статус
        try:
            bot.delete_message(message.chat.id, final_status_id)
        except:
            pass

    except Exception as e:
        print(f"Критична помилка: {e}")
        bot.reply_to(message, f"❌ Сталася помилка: {e}")
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)

# --- 5. ЗАПУСК ---
if __name__ == "__main__":
    # Веб-сервер у фоні для Render
    threading.Thread(target=run_web, daemon=True).start()
    
    print("🚀 Бот запускається з активним циклом...")
    while True:
        try:
            # Збільшені таймаути для стабільності з'єднання
            bot.infinity_polling(timeout=90, long_polling_timeout=60)
        except Exception as e:
            print(f"⚠️ Рестарт через помилку: {e}")
            time.sleep(10)
              
