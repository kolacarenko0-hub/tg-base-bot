import os
import time
import threading
import telebot
import fitz  # PyMuPDF
import docx
from openai import OpenAI
from io import BytesIO
from flask import Flask

# --- 1. ВЕБ-СЕРВЕР ДЛЯ RENDER (Health Check) ---
web_app = Flask(__name__)

@web_app.route('/')
def health_check():
    return "Bot is alive!", 200

def run_web():
    port = int(os.environ.get("PORT", 10000))
    web_app.run(host="0.0.0.0", port=port)

# --- 2. НАЛАШТУВАННЯ ТА ПЕРЕВІРКА ---
# Отримуємо токен саме з назви TELEGRAM_BOT_TOKEN
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
AI_KEY = os.environ.get("OPENAI_API_KEY")

print("--- СТАТУС ПІДКЛЮЧЕННЯ ---")
if not TOKEN:
    print("❌ ПОМИЛКА: TELEGRAM_BOT_TOKEN не знайдено в налаштуваннях Render!")
else:
    print(f"✅ Токен отримано (довжина: {len(TOKEN)} симв.)")

if not AI_KEY:
    print("❌ ПОМИЛКА: OPENAI_API_KEY не знайдено!")
else:
    print("✅ Ключ OpenAI отримано.")
print("--------------------------")

if not TOKEN or not AI_KEY:
    exit(1)

bot = telebot.TeleBot(TOKEN)
client = OpenAI(api_key=AI_KEY)

# --- 3. ОБРОБКА ФАЙЛІВ ---
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
        print(f"Помилка зчитування: {e}")
    return text

def process_with_ai(chat_id, status_msg_id, raw_text):
    all_results = []
    step = 4500  # Трохи менший крок для стабільності
    chunks = [raw_text[i:i+step] for i in range(0, len(raw_text), step)]
    total = len(chunks)
    
    for idx, chunk in enumerate(chunks, 1):
        try:
            bot.edit_message_text(f"🧠 Аналіз бази: {int((idx/total)*100)}% [{idx}/{total}]", chat_id, status_msg_id)
        except:
            pass

        try:
            res = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": f"Ти техредактор. Створи базу знань. Використовуй LaTeX для формул. Текст: {chunk}"}],
                temperature=0.3
            )
            all_results.append(res.choices[0].message.content)
        except Exception as e:
            all_results.append(f"\n[Помилка обробки частини {idx}]\n")
            
    return "\n\n".join(all_results)

# --- 4. КОМАНДИ БОТА ---
@bot.message_handler(commands=['start'])
def welcome(message):
    bot.reply_to(message, "🫡 Бот у строю! Надсилайте PDF або DOCX файл, і я зроблю з нього базу знань.")

@bot.message_handler(content_types=['document'])
def handle_file(message):
    file_name = message.document.file_name
    ext = file_name.split('.')[-1].lower()
    temp_path = f"temp_{message.chat.id}.tmp"
    
    if ext not in ['pdf', 'docx']:
        bot.reply_to(message, "❌ Формат не підтримується. Тільки PDF або DOCX.")
        return

    status = bot.reply_to(message, "📥 Завантажую файл...")
    try:
        file_info = bot.get_file(message.document.file_id)
        downloaded = bot.download_file(file_info.file_path)
        with open(temp_path, "wb") as f:
            f.write(downloaded)

        bot.edit_message_text("📄 Зчитую текст...", message.chat.id, status.message_id)
        text = extract_text(temp_path, ext)
        
        if not text.strip():
            bot.edit_message_text("❌ Не вдалося витягти текст із файлу.", message.chat.id, status.message_id)
            return

        result = process_with_ai(message.chat.id, status.message_id, text)

        out = BytesIO()
        out.name = "base.txt"
        out.write(result.encode('utf-8'))
        out.seek(0)

        bot.send_document(message.chat.id, out, caption=f"✅ Обробка завершена: {file_name}")
        bot.delete_message(message.chat.id, status.message_id)
    except Exception as e:
        bot.reply_to(message, f"❌ Сталася помилка: {e}")
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)

# --- 5. ЗАПУСК ---
if __name__ == "__main__":
    # Запуск Flask у фоновому потоці
    threading.Thread(target=run_web, daemon=True).start()
    
    print("🚀 Бот запускається...")
    while True:
        try:
            bot.infinity_polling(timeout=60, long_polling_timeout=30)
        except Exception as e:
            print(f"⚠️ Перезапуск через помилку: {e}")
            time.sleep(10)
