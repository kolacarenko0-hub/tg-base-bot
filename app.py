import os
import time
import threading
import re
import gc
import telebot
import fitz  # PyMuPDF
import docx
from openai import OpenAI
from flask import Flask
from PIL import Image
import pytesseract

# --- 1. СЕРВЕР ---
web_app = Flask(__name__)
@web_app.route('/')
def health_check(): return "Hybrid Analyst Active", 200

def run_web():
    port = int(os.environ.get("PORT", 10000))
    web_app.run(host="0.0.0.0", port=port)

# --- 2. КОНФІГУРАЦІЯ ---
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
AI_KEY = os.environ.get("OPENAI_API_KEY")
bot = telebot.TeleBot(TOKEN)
client = OpenAI(api_key=AI_KEY)

# --- 3. ФУНКЦІЇ ЗЧИТУВАННЯ ---

def extract_from_pdf(file_path):
    """Просте текстове зчитування PDF (без OCR)"""
    text = ""
    with fitz.open(file_path) as doc:
        for page in doc:
            text += page.get_text()
    return text

def extract_from_docx(file_path):
    """Зчитування тексту з файлів Word"""
    doc = docx.Document(file_path)
    return "\n".join([para.text for para in doc.paragraphs])

def extract_from_image(file_path):
    """Зчитування тексту з фото/скріншота через OCR"""
    img = Image.open(file_path)
    # Оптимізація для ч/б для кращого розпізнавання
    text = pytesseract.image_to_string(img, lang='ukr+eng')
    return text

# --- 4. АНАЛІЗ ЧЕРЕЗ AI ---
def ask_ai(content, user_query):
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Ти військовий аналітик. Опрацюй наданий текст згідно з запитом користувача. Відповідай чітко, структуруй головне."},
                {"role": "user", "content": f"Запит: {user_query}\n\nТекст для аналізу:\n{content[:8000]}"}
            ],
            temperature=0.2
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"Помилка AI: {e}"

# --- 5. ОБРОБНИКИ ТЕЛЕГРАМ ---

# Обробка фото (скріншоти)
@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    status = bot.reply_to(message, "📸 Бачу скріншот. Розпізнаю текст...")
    try:
        file_info = bot.get_file(message.photo[-1].file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        temp_img = f"img_{message.chat.id}.png"
        
        with open(temp_img, 'wb') as f:
            f.write(downloaded_file)
        
        text = extract_from_image(temp_img)
        query = message.caption if message.caption else "Зроби загальний аналіз"
        
        if text.strip():
            result = ask_ai(text, query)
            bot.reply_to(message, result)
        else:
            bot.reply_to(message, "❌ Не вдалося розпізнати текст на зображенні.")
            
        os.remove(temp_img)
    except Exception as e:
        bot.reply_to(message, f"Помилка: {e}")
    finally:
        bot.delete_message(message.chat.id, status.message_id)
        gc.collect()

# Обробка документів (PDF, DOCX)
@bot.message_handler(content_types=['document'])
def handle_docs(message):
    file_name = message.document.file_name.lower()
    status = bot.reply_to(message, "📄 Опрацьовую документ...")
    temp_path = f"file_{message.chat.id}_{file_name}"
    
    try:
        file_info = bot.get_file(message.document.file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        
        with open(temp_path, 'wb') as f:
            f.write(downloaded_file)
        
        text = ""
        if file_name.endswith('.pdf'):
            text = extract_from_pdf(temp_path)
        elif file_name.endswith('.docx'):
            text = extract_from_docx(temp_path)
        else:
            bot.reply_to(message, "❌ Формат не підтримується. Тільки PDF, DOCX або Фото.")
            return

        if text.strip():
            query = message.caption if message.caption else "Зроби витяг головного"
            result = ask_ai(text, query)
            
            # Якщо відповідь довга, відправляємо як файл або частинами
            if len(result) > 4000:
                with open("result.txt", "w", encoding="utf-8") as f:
                    f.write(result)
                with open("result.txt", "rb") as f:
                    bot.send_document(message.chat.id, f)
            else:
                bot.reply_to(message, result)
        else:
            bot.reply_to(message, "❌ В файлі не знайдено тексту (можливо це скан? Спробуй надіслати скріншотом).")

    except Exception as e:
        bot.reply_to(message, f"Помилка: {e}")
    finally:
        if os.path.exists(temp_path): os.remove(temp_path)
        bot.delete_message(message.chat.id, status.message_id)
        gc.collect()

# --- 6. ЗАПУСК ---
if __name__ == "__main__":
    threading.Thread(target=run_web, daemon=True).start()
    bot.infinity_polling(timeout=90)
        
