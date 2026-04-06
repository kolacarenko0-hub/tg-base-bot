import os
import time
import threading
import gc
import telebot
import fitz
import docx
from openai import OpenAI
from flask import Flask
from PIL import Image
import pytesseract

# --- 1. СЕРВЕР ---
web_app = Flask(__name__)
@web_app.route('/')
def health_check(): return "Scanner Bot Active", 200

def run_web():
    port = int(os.environ.get("PORT", 10000))
    web_app.run(host="0.0.0.0", port=port)

# --- 2. КОНФІГУРАЦІЯ ---
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
AI_KEY = os.environ.get("OPENAI_API_KEY")
bot = telebot.TeleBot(TOKEN)
client = OpenAI(api_key=AI_KEY)

# --- 3. ФУНКЦІЇ ЗЧИТУВАННЯ ---

def extract_text_from_pdf(path):
    """Витягує текст зі збереженням блочної структури (для таблиць)"""
    text = ""
    try:
        with fitz.open(path) as doc:
            for page in doc:
                # "blocks" краще зберігає структуру колонок та таблиць
                blocks = page.get_text("blocks")
                for b in blocks:
                    text += b[4] + "\n"
                text += "\n" + "-"*20 + "\n"
    except Exception as e:
        print(f"PDF Error: {e}")
    return text

def extract_text_from_img(path):
    """OCR для скріншотів"""
    try:
        img = Image.open(path)
        # Збільшуємо чіткість для таблиць
        text = pytesseract.image_to_string(img, lang='ukr+eng', config='--psm 6') 
        return text
    except:
        return ""

# --- 4. ОБРОБКА ЧЕРЕЗ AI (ФОРМАТУВАННЯ) ---
# --- ОНОВЛЕНА ФУНКЦІЯ ФОРМАТУВАННЯ ---
def format_content(raw_text, user_caption):
    # Якщо в підписі до фото є назва міни, використаємо її як заголовок
    title = user_caption if user_caption else "ОБ'ЄКТ (БЕЗ НАЗВИ)"
    
    try:
        res = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": """Ти — військовий технічний секретар. 
                Твоє завдання: оцифрувати текст зі скріншотів технічної документації.
                
                СТРУКТУРА ВИВОДУ:
                1. НА ПОЧАТКУ: Великий заголовок (назва міни).
                2. РОЗПОДІЛ ЗА БЛОКАМИ:
                   ### ЗАГАЛЬНІ ВІДОМОСТІ
                   ### ТЕХНІКО-ТАКТИЧНІ ХАРАКТЕРИСТИКИ (ТТХ)
                   ### ДОДАТКОВІ ВІДОМОСТІ / ОСОБЛИВОСТІ
                
                ПРАВИЛА ОФОРМЛЕННЯ:
                - ЗАБОРОНЕНО малювати таблиці символами | або -.
                - ЗАМІСТЬ ТАБЛИЦЬ використовуй формат: **Назва параметра** — Значення (кожне з нового рядка).
                - Якщо текст стосується мін, групуй характеристики (вага, тип підривника, радіус ураження тощо) у блок ТТХ.
                - Текст має бути чистим, без твоїх коментарів."""},
                {"role": "user", "content": f"НАЗВА: {title}\n\nТЕКСТ ЗІ СКРІНШОТІВ:\n{raw_text[:15000]}"}
            ],
            temperature=0.1
        )
        return res.choices[0].message.content
    except Exception as e:
        return f"Помилка обробки: {e}"

# --- 5. ОБРОБНИКИ ---

@bot.message_handler(content_types=['photo', 'document'])
def handle_files(message):
    status = bot.reply_to(message, "📥 Зчитую дані та формую документ...")
    temp_path = f"input_{message.chat.id}"
    res_path = f"result_{message.chat.id}.docx"
    
    try:
        # Завантаження файлу або фото
        if message.content_type == 'photo':
            file_info = bot.get_file(message.photo[-1].file_id)
            temp_path += ".png"
            with open(temp_path, "wb") as f:
                f.write(bot.download_file(file_info.file_path))
            raw_text = extract_text_from_img(temp_path)
        else:
            fname = message.document.file_name.lower()
            temp_path += f"_{fname}"
            file_info = bot.get_file(message.document.file_id)
            with open(temp_path, "wb") as f:
                f.write(bot.download_file(file_info.file_path))
            
            if fname.endswith('.pdf'):
                raw_text = extract_text_from_pdf(temp_path)
            elif fname.endswith('.docx'):
                doc = docx.Document(temp_path)
                raw_text = "\n".join([p.text for p in doc.paragraphs])
            else:
                bot.reply_to(message, "❌ Формат не підтримується.")
                return

        # Форматування через AI
        formatted_text = format_content(raw_text)

        # Створення вихідного DOCX файлу
        output_doc = docx.Document()
        output_doc.add_paragraph(formatted_text)
        output_doc.save(res_path)

        # Відправка результату
        with open(res_path, "rb") as f:
            bot.send_document(message.chat.id, f, caption="✅ Текст оцифровано та збережено у файл.")

    except Exception as e:
        bot.reply_to(message, f"⚠️ Помилка: {e}")
    finally:
        # Очищення
        for p in [temp_path, res_path]:
            if os.path.exists(p): os.remove(p)
        bot.delete_message(message.chat.id, status.message_id)
        gc.collect()

# --- 6. ЗАПУСК ---
if __name__ == "__main__":
    threading.Thread(target=run_web, daemon=True).start()
    bot.remove_webhook()
    time.sleep(1)
    print("Бот готовий до зчитування!")
    bot.infinity_polling()
