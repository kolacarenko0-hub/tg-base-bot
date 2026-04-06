import os
import time
import threading
import gc
import re
import telebot
import fitz
import docx
from openai import OpenAI
from flask import Flask
from PIL import Image
import pytesseract

# --- 1. ВЕБ-СЕРВЕР ДЛЯ RENDER (Щоб не було Port Timeout) ---
web_app = Flask(__name__)

@web_app.route('/')
def health_check():
    return "Military Scanner Bot is running!", 200

def run_web():
    # Render автоматично надає порт через змінну PORT
    port = int(os.environ.get("PORT", 10000))
    # host="0.0.0.0" обов'язковий для зовнішнього доступу на Render
    web_app.run(host="0.0.0.0", port=port)

# --- 2. НАЛАШТУВАННЯ ---
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
AI_KEY = os.environ.get("OPENAI_API_KEY")

bot = telebot.TeleBot(TOKEN)
client = OpenAI(api_key=AI_KEY)

# --- 3. ФУНКЦІЇ ЗЧИТУВАННЯ ---

def extract_text_from_pdf(path):
    text = ""
    try:
        with fitz.open(path) as doc:
            for page in doc:
                text += page.get_text("blocks_text") if hasattr(page, 'get_text') else page.get_text()
                text += "\n\n"
    except Exception as e:
        print(f"PDF Error: {e}")
    return text

def extract_text_from_img(path):
    try:
        img = Image.open(path)
        # Режим psm 6 оптимізований для блоків тексту та таблиць
        text = pytesseract.image_to_string(img, lang='ukr+eng', config='--psm 6')
        return text
    except:
        return ""

# --- 4. ЛОГІКА ОЦИФРУВАННЯ (КЛЮЧ-ЗНАЧЕННЯ) ---

def format_to_military_struct(raw_text, user_caption):
    # Використовуємо підпис користувача як назву об'єкта
    title = user_caption.strip() if user_caption else "ОБ'ЄКТ (БЕЗ НАЗВИ)"
    
    try:
        res = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": """Ти — військовий технічний секретар. 
                Твоє завдання: оцифрувати текст зі скріншотів або документів.
                
                СТРУКТУРА ВИВОДУ:
                1. НА ПОЧАТКУ: Назва об'єкта (великим шрифтом).
                2. РОЗПОДІЛ ЗА БЛОКАМИ:
                   ### ЗАГАЛЬНІ ВІДОМОСТІ
                   ### ТЕХНІКО-ТАКТИЧНІ ХАРАКТЕРИСТИКИ (ТТХ)
                   ### ДОДАТКОВІ ВІДОМОСТІ
                
                ПРАВИЛА ОФОРМЛЕННЯ:
                - ЗАБОРОНЕНО малювати таблиці символами | або -.
                - ЗАМІСТЬ ТАБЛИЦЬ використовуй формат: **Назва параметра** — Значення (кожне з нового рядка).
                - Якщо дані стосуються мін, ТТХ мають включати: вагу, тип підривника, датчики, радіус, час самоліквідації тощо.
                - Текст має бути структурованим для легкого зчитування іншим ШІ. Без вступних слів."""},
                {"role": "user", "content": f"НАЗВА: {title}\n\nСИРИЙ ТЕКСТ:\n{raw_text[:12000]}"}
            ],
            temperature=0.1
        )
        return res.choices[0].message.content
    except Exception as e:
        return f"Помилка ШІ: {e}"

# --- 5. ОБРОБНИКИ ПОВІДОМЛЕНЬ ---

@bot.message_handler(content_types=['photo', 'document'])
def handle_files(message):
    status = bot.reply_to(message, "⚙️ Опрацьовую дані...")
    temp_path = f"input_{message.chat.id}"
    res_path = f"struct_{message.chat.id}.docx"
    
    try:
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
                d = docx.Document(temp_path)
                raw_text = "\n".join([p.text for p in d.paragraphs])
            else:
                bot.reply_to(message, "❌ Формат не підтримується (тільки PDF, DOCX або Фото).")
                return

        # Оцифрування
        caption = message.caption if message.caption else ""
        formatted_data = format_to_military_struct(raw_text, caption)

        # Створення DOCX
        doc_out = docx.Document()
        for line in formatted_data.split('\n'):
            if line.startswith('###'):
                doc_out.add_heading(line.replace('###', '').strip(), level=3)
            else:
                doc_out.add_paragraph(line)
        doc_out.save(res_path)

        # Відправка
        with open(res_path, "rb") as f:
            bot.send_document(message.chat.id, f, caption="✅ Дані структуровані у форматі Ключ-Значення.")

    except Exception as e:
        bot.reply_to(message, f"❌ Помилка: {e}")
    finally:
        for p in [temp_path, res_path]:
            if os.path.exists(p): os.remove(p)
        bot.delete_message(message.chat.id, status.message_id)
        gc.collect()

# --- 6. ЗАПУСК (ВІДПОВІДНО ДО ВИМОГ RENDER) ---

if __name__ == "__main__":
    # Спочатку запускаємо Flask у фоновому потоці
    t = threading.Thread(target=run_web)
    t.daemon = True
    t.start()
    
    # Видаляємо вебхуки для уникнення помилки 409
    try:
        bot.remove_webhook()
        time.sleep(1)
    except:
        pass
    
    print("Сервіс запущено. Очікування повідомлень...")
    
    # Запуск бота
    bot.infinity_polling(timeout=90, long_polling_timeout=5)
