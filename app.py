import os
import time
import threading
import gc
import telebot
import fitz  # PyMuPDF
import docx
from openai import OpenAI
from flask import Flask
from PIL import Image
import pytesseract

# --- 1. ВЕБ-СЕРВЕР (Для запобігання Port Timeout на Render) ---
web_app = Flask(__name__)

@web_app.route('/')
def health_check():
    return "Military Scanner Active", 200

def run_web():
    port = int(os.environ.get("PORT", 10000))
    web_app.run(host="0.0.0.0", port=port)

# --- 2. КОНФІГУРАЦІЯ (Змінні оточення) ---
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
AI_KEY = os.environ.get("OPENAI_API_KEY")
bot = telebot.TeleBot(TOKEN)
client = OpenAI(api_key=AI_KEY)

# Буфер для збереження тексту (chat_id: {data})
user_data_buffer = {}
buffer_lock = threading.Lock()

# --- 3. ШВИДКИЙ OCR (Оптимізовано для Render) ---
def fast_ocr(file_path):
    try:
        with Image.open(file_path) as img:
            # Зменшуємо розмір для економії RAM (Render дає лише 512МБ)
            img.thumbnail((1500, 1500))
            img = img.convert('L') # Чорно-білий режим прискорює зчитування
            text = pytesseract.image_to_string(img, lang='ukr+eng', config='--psm 6')
            return text
    except Exception as e:
        print(f"Помилка OCR: {e}")
        return ""

# --- 4. ФОРМУВАННЯ ЗВІТУ ЧЕРЕЗ AI ---
def finalize_and_send(chat_id):
    with buffer_lock:
        data = user_data_buffer.get(chat_id)
        if not data or not data['text'].strip():
            return
        
        raw_content = data['text']
        title = data['caption'] if data['caption'] else "ОБ'ЄКТ БЕЗ НАЗВИ"
    
    res_path = f"report_{chat_id}.docx"
    try:
        # Запит до GPT-4o-mini для структурування
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": """Ти — військовий технічний секретар. 
                Згрупуй текст з кількох скріншотів в один структурований звіт.
                СТРУКТУРА:
                ### НАЗВА ОБ'ЄКТА
                ### ЗАГАЛЬНІ ВІДОМОСТІ
                ### ТЕХНІКО-ТАКТИЧНІ ХАРАКТЕРИСТИКИ (ТТХ)
                ### ДОДАТКОВІ ВІДОМОСТІ
                ПРАВИЛА:
                - ТАБЛИЦІ ЗАБОРОНЕНІ. Формат: **Параметр** — Значення.
                - Виправляй помилки OCR. Пиши стисло та професійно."""},
                {"role": "user", "content": f"НАЗВА: {title}\n\nТЕКСТ:\n{raw_content}"}
            ],
            temperature=0
        )
        
        final_text = response.choices[0].message.content
        
        # Створення документа
        doc = docx.Document()
        for line in final_text.split('\n'):
            if line.startswith('###'):
                doc.add_heading(line.replace('###', '').strip(), level=3)
            else:
                doc.add_paragraph(line)
        
        doc.save(res_path)
        with open(res_path, "rb") as f:
            bot.send_document(chat_id, f, caption=f"✅ Об'єкт оцифровано: {title}")

    except Exception as e:
        bot.send_message(chat_id, f"❌ Помилка AI: {e}")
    finally:
        with buffer_lock:
            user_data_buffer.pop(chat_id, None)
        if os.path.exists(res_path): 
            os.remove(res_path)
        gc.collect()

# --- 5. ОБРОБНИКИ ПОВІДОМЛЕНЬ ---
def photo_worker(message):
    chat_id = message.chat.id
    try:
        file_info = bot.get_file(message.photo[-1].file_id)
        temp_file = f"img_{chat_id}_{time.time()}.png"
        
        downloaded = bot.download_file(file_info.file_path)
        with open(temp_file, 'wb') as f:
            f.write(downloaded)
        
        text = fast_ocr(temp_file)
        
        with buffer_lock:
            if chat_id in user_data_buffer:
                user_data_buffer[chat_id]['text'] += f"\n{text}"
                if message.caption:
                    user_data_buffer[chat_id]['caption'] = message.caption
        
        if os.path.exists(temp_file): 
            os.remove(temp_file)
    except Exception as e:
        print(f"Worker Error: {e}")

@bot.message_handler(content_types=['photo'])
def handle_photos(message):
    chat_id = message.chat.id
    with buffer_lock:
        if chat_id not in user_data_buffer:
            user_data_buffer[chat_id] = {'text': '', 'caption': message.caption, 'timer': None}
            bot.send_message(chat_id, "📥 Скріншоти отримано. Починаю зчитування...")

        if user_data_buffer[chat_id]['timer']:
            user_data_buffer[chat_id]['timer'].cancel()
        
        # Запуск OCR у фоновому потоці
        threading.Thread(target=photo_worker, args=(message,), daemon=True).start()
        
        # Чекаємо 10 секунд після останнього фото в альбомі
        t = threading.Timer(10.0, finalize_and_send, args=[chat_id])
        user_data_buffer[chat_id]['timer'] = t
        t.start()

# --- 6. СТАРТ З ЗАХИСТОМ ВІД КОНФЛІКТІВ ---
if __name__ == "__main__":
    # 1. Запуск веб-сервера
    threading.Thread(target=run_web, daemon=True).start()
    
    # 2. Очищення старих сесій (Рішення для 409)
    try:
        print("Ініціалізація... Очищення старих сесій.")
        bot.remove_webhook()
        time.sleep(2)
        # Ігноруємо все, що прийшло, поки бот був вимкнений
        bot.get_updates(offset=-1, timeout=1) 
        print("Чергу очищено. Пауза 15 секунд для стабілізації Render...")
        time.sleep(15)
    except Exception as e:
        print(f"Помилка при старті: {e}")
    
    print("--- БОТ ЗАПУЩЕНИЙ І ГОТОВИЙ ---")
    
    # 3. Постійне опитування з авто-перезапуском
    while True:
        try:
            bot.polling(none_stop=True, interval=3, timeout=60)
        except Exception as e:
            print(f"Помилка з'єднання: {e}. Перезапуск через 10 сек...")
            time.sleep(10)
        
