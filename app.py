import os
import time
import threading
import telebot
import fitz
import docx
from openai import OpenAI
from io import BytesIO
from flask import Flask

web_app = Flask(__name__)
@web_app.route('/')
def health_check(): return "Bot is active!", 200

def run_web():
    port = int(os.environ.get("PORT", 10000))
    web_app.run(host="0.0.0.0", port=port)

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
AI_KEY = os.environ.get("OPENAI_API_KEY")

bot = telebot.TeleBot(TOKEN)
client = OpenAI(api_key=AI_KEY)

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
        print(f"Помилка файлу: {e}")
    return text

def process_with_ai(chat_id, initial_status_id, raw_text):
    # Тепер ми НЕ створюємо гігантський список all_results
    step = 4000 
    chunks = [raw_text[i:i+step] for i in range(0, len(raw_text), step)]
    total = len(chunks)
    
    current_status_id = initial_status_id
    output_filename = f"result_{chat_id}.txt"

    # Очищуємо файл перед початком
    with open(output_filename, "w", encoding="utf-8") as f:
        f.write("")

    for idx, chunk in enumerate(chunks, 1):
        try:
            bot.delete_message(chat_id, current_status_id)
        except: pass

        new_msg = bot.send_message(chat_id, f"⏳ **Обробка частини {idx}/{total}**\nПам'ять очищена, працюю далі...", parse_mode="Markdown")
        current_status_id = new_msg.message_id

        try:
            res = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": f"Зроби базу знань (LaTeX). Текст: {chunk}"}],
                temperature=0.2
            )
            # ВІДРАЗУ ЗАПИСУЄМО У ФАЙЛ (це звільняє RAM)
            with open(output_filename, "a", encoding="utf-8") as f:
                f.write(res.choices[0].message.content + "\n\n")
            
            # Примусово очищуємо кеш змінних, якщо можливо
            res = None 
        except Exception as e:
            with open(output_filename, "a", encoding="utf-8") as f:
                f.write(f"\n[Помилка в частині {idx}]\n")
            
        time.sleep(1)
            
    return output_filename, current_status_id

@bot.message_handler(commands=['start'])
def welcome(message):
    bot.reply_to(message, "🫡 Бот готовий до великих файлів! Скидайте документ.")

@bot.message_handler(content_types=['document'])
def handle_file(message):
    file_name = message.document.file_name
    ext = file_name.split('.')[-1].lower()
    temp_path = f"raw_{message.chat.id}.tmp"
    
    if ext not in ['pdf', 'docx']:
        bot.reply_to(message, "❌ Тільки PDF/DOCX.")
        return

    status = bot.reply_to(message, "📥 Завантаження...")
    
    try:
        file_info = bot.get_file(message.document.file_id)
        downloaded = bot.download_file(file_info.file_path)
        with open(temp_path, "wb") as f:
            f.write(downloaded)

        text = extract_text(temp_path, ext)
        # Очищуємо пам'ять від сирого завантаженого файлу відразу
        if os.path.exists(temp_path): os.remove(temp_path)

        res_file, final_status_id = process_with_ai(message.chat.id, status.message_id, text)

        with open(res_file, "rb") as f:
            bot.send_document(message.chat.id, f, caption=f"✅ Готово! Оброблено {file_name}")
        
        if os.path.exists(res_file): os.remove(res_file)
        bot.delete_message(message.chat.id, final_status_id)

    except Exception as e:
        bot.reply_to(message, f"❌ Помилка: {e}")

if __name__ == "__main__":
    threading.Thread(target=run_web, daemon=True).start()
    bot.infinity_polling(timeout=90, long_polling_timeout=60)
