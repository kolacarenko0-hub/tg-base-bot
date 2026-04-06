import os
import telebot
import fitz
import docx
import gc
from openai import OpenAI
from flask import Flask
from PIL import Image
import pytesseract
import threading

# --- СЕРВЕР ДЛЯ RENDER ---
web_app = Flask(__name__)
@web_app.route('/')
def health_check(): return "Analyst Bot is Alive", 200

# --- НАЛАШТУВАННЯ ---
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
AI_KEY = os.environ.get("OPENAI_API_KEY")
bot = telebot.TeleBot(TOKEN)
client = OpenAI(api_key=AI_KEY)

# --- ФУНКЦІЇ ЗЧИТУВАННЯ ---

def get_pdf_text(path):
    text = ""
    try:
        with fitz.open(path) as doc:
            # Читаємо максимум перші 15 сторінок, щоб не "покласти" RAM
            for i in range(min(len(doc), 15)):
                text += doc[i].get_text()
    except Exception as e:
        print(f"PDF Error: {e}")
    return text

def get_docx_text(path):
    try:
        doc = docx.Document(path)
        return "\n".join([p.text for p in doc.paragraphs])
    except:
        return ""

def get_image_text(path):
    try:
        # Відкриваємо і відразу оптимізуємо розмір
        img = Image.open(path)
        img.thumbnail((1500, 1500)) 
        return pytesseract.image_to_string(img, lang='ukr+eng')
    except Exception as e:
        return f"OCR Error: {e}"

def analyze_text(content, query):
    if not content.strip():
        return "❌ Не вдалося витягнути текст із файлу. Переконайтеся, що це не 'картинка в PDF' (тоді краще зробіть скріншот)."
    
    try:
        res = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Ти військовий аналітик. Коротко і чітко дай відповідь за текстом."},
                {"role": "user", "content": f"Запит: {query}\n\nТекст:\n{content[:7000]}"}
            ]
        )
        return res.choices[0].message.content
    except Exception as e:
        return f"Помилка OpenAI: {e}"

# --- ОБРОБНИКИ ТЕЛЕГРАМ ---

@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    status = bot.reply_to(message, "🔍 Обробляю скріншот...")
    path = f"img_{message.chat.id}.png"
    try:
        file_info = bot.get_file(message.photo[-1].file_id)
        with open(path, "wb") as f:
            f.write(bot.download_file(file_info.file_path))
        
        text = get_image_text(path)
        ans = analyze_text(text, message.caption or "Проаналізуй")
        bot.reply_to(message, ans)
    finally:
        if os.path.exists(path): os.remove(path)
        bot.delete_message(message.chat.id, status.message_id)
        gc.collect()

@bot.message_handler(content_types=['document'])
def handle_doc(message):
    fname = message.document.file_name.lower()
    status = bot.reply_to(message, "📄 Читаю документ...")
    path = f"doc_{message.chat.id}_{fname}"
    
    try:
        file_info = bot.get_file(message.document.file_id)
        with open(path, "wb") as f:
            f.write(bot.download_file(file_info.file_path))
        
        text = ""
        if fname.endswith('.pdf'):
            text = get_pdf_text(path)
        elif fname.endswith('.docx'):
            text = get_docx_text(path)
        
        ans = analyze_text(text, message.caption or "Зроби витяг")
        bot.reply_to(message, ans)
    finally:
        if os.path.exists(path): os.remove(path)
        bot.delete_message(message.chat.id, status.message_id)
        gc.collect()

# --- ЗАПУСК ---
def run_flask():
    port = int(os.environ.get("PORT", 10000))
    web_app.run(host="0.0.0.0", port=port)

if __name__ == "__main__":
    # Запускаємо Flask у окремому потоці для Render
    threading.Thread(target=run_flask, daemon=True).start()
    
    # Видаляємо старий веб-хук, щоб прибрати помилку 409
    bot.remove_webhook()
    time.sleep(1) # Невелика пауза для стабілізації
    
    print("Бот запущений успішно через Long Polling...")
    
    # Запускаємо нескінченне опитування
    bot.infinity_polling(timeout=90, long_polling_timeout=5)
