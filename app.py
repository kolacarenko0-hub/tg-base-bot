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
    # Порт 10000 для Render
    port = int(os.environ.get("PORT", 10000))
    web_app.run(host="0.0.0.0", port=port)

# --- 2. НАЛАШТУВАННЯ ТА ДІАГНОСТИКА ---
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
AI_KEY = os.environ.get("OPENAI_API_KEY")

print("--- ДІАГНОСТИКА ЗАПУСКУ ---")
if TOKEN:
    # Виводимо тільки початок і кінець для безпеки
    print(f"✅ Токен знайдено: {TOKEN[:5]}...{TOKEN[-5:]}")
    print(f"📏 Довжина токена: {len(TOKEN)} символів")
else:
    print("❌ ПОМИЛКА: TELEGRAM_BOT_TOKEN не знайдено в Environment Variables!")

if AI_KEY:
    print(f"✅ Ключ OpenAI знайдено: {AI_KEY[:5]}...")
else:
    print("❌ ПОМИЛКА: OPENAI_API_KEY не знайдено!")
print("---------------------------")

if not TOKEN or not AI_KEY:
    print("🛑 Зупинка: Відсутні критичні налаштування.")
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

def process_with_ai(chat_id, status_msg_id, raw_text):
    all_results = []
    step = 5000 
    chunks = [raw_text[i:i+step] for i in range(0, len(raw_text), step)]
    total = len(chunks)
    
    for idx, chunk in enumerate(chunks, 1):
        progress = int((idx / total) * 100)
        try:
            bot.edit_message_text(f"🧠 Аналіз бази: {progress}% [{idx}/{total}]", chat_id, status_msg_id)
        except:
            pass

        prompt = f"Ти техредактор. Створи базу знань. ### [НАЗВА]. Формули: LaTeX. Текст: {chunk}"
        try:
            res = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2
            )
            all_results.append(res.choices[0].message.content)
        except Exception as e:
            print(f"Помилка OpenAI на частині {idx}: {e}")
            all_results.append(f"\n[Помилка обробки частини {idx}]\n")
            
    return "\n\n".join(all_results)

# --- 4. ОБРОБНИКИ TELEGRAM ---
@bot.message_handler(commands=['start'])
def welcome(message):
    bot.
