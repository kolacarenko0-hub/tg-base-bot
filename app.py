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

# --- 1. ВЕБ-СЕРВЕР ДЛЯ RENDER ---
web_app = Flask(__name__)

@web_app.route('/')
def health_check():
    return "Scanner Pro Active", 200

def run_web():
    # Порт за замовчуванням 10000 для Render
    port = int(os.environ.get("PORT", 10000))
    web_app.run(host="0.0.0.0", port=port)

# --- 2. КОНФІГУРАЦІЯ ---
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
AI_KEY = os.environ.get("OPENAI_API_KEY")
bot = telebot.TeleBot(TOKEN)
client = OpenAI(api_key=AI_KEY)

# Глобальні змінні для накопичення даних
user_data_buffer = {}
buffer_lock = threading.Lock()

# --- 3. ФУНКЦІЇ ОБРОБКИ (OCR) ---
def fast_ocr(file_path):
    try:
        with Image.open(file_path) as img:
            # Стискаємо для швидкості на слабкому CPU
            img.thumbnail((1500, 1500))
            img = img.convert('L') 
            text = pytesseract.image_to_string(img, lang='ukr+eng', config='--psm 6')
            return text
    except Exception as e:
        print(f"Помилка OCR: {e}")
        return ""

# --- 4. ФОРМУВАННЯ ФІНАЛЬНОГО ЗВІТУ (AI) ---
def finalize_and_send(chat_id):
    with buffer_lock:
        data = user_data_buffer.get(chat_id)
        if not data or not data['text'].strip():
            return
        
        raw_content = data['text']
        title = data['caption'] if data['caption'] else "ОБ'ЄКТ БЕЗ НАЗВИ"
    
    res_path = f"final_{chat_id}.docx"
    try:
        # Запит до OpenAI для структурування "Ключ — Значення"
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": """Ти — військовий технічний секретар. 
                Згрупуй текст з кількох скріншотів в один звіт.
                СТРУКТУРА:
                ### НАЗВА ОБ'ЄКТА
                ### ЗАГАЛЬНІ ВІДОМОСТІ
                ### ТЕХНІКО-ТАКТИЧНІ ХАРАКТЕРИСТИКИ (ТТХ)
                ### ДОДАТКОВІ ВІДОМОСТІ
                ПРАВИЛА:
                - ЗАБОРОНЕНО таблиці. Використовуй: **Параметр** — Значення.
                - Виправляй помилки зчитування. Ніякої зайвої "води"."""},
                {"role": "user", "content": f"ОБ'ЄКТ: {title}\n\nТЕКСТ:\n{raw_content}"}
            ],
            temperature=0
        )
        
        final_text = response.choices[0].message.content
        
        # Створення DOCX файлу
        doc = docx.Document()
        for line in final_text.split('\n'):
            if line.startswith('###'):
                doc.add_heading(line.replace('###', '').strip(), level=3)
            else:
                doc.add_paragraph(line)
        
        doc.save(res_path)
        with open(res_path, "rb") as f:
            bot.send_document(chat_id, f, caption=f"✅ Звіт сформовано: {title}")

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
        temp_file = f"tmp_{chat_id}_{time.time()}.png"
        
        downloaded_file = bot.download_file(file_info.file_path)
        with open(temp_file, 'wb') as f:
            f.write(downloaded_file)
        
        text = fast_ocr(temp_file)
        
        with buffer_lock:
            if chat_id in user_data_buffer:
                user_data_buffer[chat_id]['text'] += f"\n{text}"
                # Якщо підпис є хоча б на одному фото, беремо його
                if message.caption:
                    user_data_buffer[chat_id]['caption'] = message.caption
        
        if os.path.exists(temp_file): 
            os.remove(temp_file)
    except Exception as e:
        print(f"Помилка воркера: {e}")

@bot.message_handler(content_types=['photo'])
def handle_photos(message):
    chat_id = message.chat.id
    with buffer_lock:
        if chat_id not in user_data_buffer:
            user_data_buffer[chat_id] = {'text': '', 'caption': message.caption, 'timer': None}
            bot.send_message(chat_id, "📥 Отримано фото. Починаю зчитування альбому...")

        # Скидаємо таймер при кожному новому фото в альбомі
        if user_data_buffer[chat_id]['timer']:
            user_data_buffer[chat_id]['timer'].cancel()
        
        # Обробляємо фото у фоновому режимі (threading), щоб не блокувати бота
        threading.Thread(target=photo_worker, args=(message,), daemon=True).start()
        
        # Чекаємо 10 секунд після останнього фото, щоб сформувати звіт
        t = threading.Timer(10.0, finalize_and_send, args=[chat_id])
        user_data_buffer[chat_id]['timer'] = t
        t.start()

# --- 6. ЗАПУСК БОТА ---
if __name__ == "__main__":
    # Запуск Flask сервера
    threading.Thread(target=run_web, daemon=True).start()
    
    # Спроба очистити чергу перед стартом
    try:
        print("Очищення стари
        
