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
def health_check(): return "Multi-Scanner Active", 200

def run_web():
    port = int(os.environ.get("PORT", 10000))
    web_app.run(host="0.0.0.0", port=port)

# --- 2. КОНФІГУРАЦІЯ ---
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
AI_KEY = os.environ.get("OPENAI_API_KEY")
bot = telebot.TeleBot(TOKEN)
client = OpenAI(api_key=AI_KEY)

# Сховище для накопичення тексту (chat_id: {"text": "...", "timer": timer_obj, "caption": "..."})
user_data_buffer = {}

# --- 3. ПРИСКОРЕНЕ ЗЧИТУВАННЯ (OCR) ---
def fast_ocr(file_path):
    try:
        with Image.open(file_path) as img:
            # Стискаємо для швидкості (Render CPU слабкий)
            img.thumbnail((1600, 1600))
            # Чорно-білий режим покращує точність і швидкість OCR
            img = img.convert('L')
            text = pytesseract.image_to_string(img, lang='ukr+eng', config='--psm 6')
            return text
    except Exception as e:
        return f"\n[Помилка OCR: {e}]\n"

# --- 4. ФІНАЛЬНЕ ОФОРМЛЕННЯ ЧЕРЕЗ AI ---
def process_combined_data(chat_id):
    data = user_data_buffer.get(chat_id)
    if not data: return

    raw_text = data['text']
    title = data['caption'] if data['caption'] else "ОБ'ЄКТ БЕЗ НАЗВИ"
    res_path = f"report_{chat_id}.docx"

    try:
        # Відправляємо весь зібраний текст в AI
        res = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": """Ти — технічний секретар. 
                Згрупуй отриманий текст у чіткі блоки:
                ### НАЗВА ОБ'ЄКТА
                ### ЗАГАЛЬНІ ВІДОМОСТІ
                ### ТЕХНІКО-ТАКТИЧНІ ХАРАКТЕРИСТИКИ (ТТХ)
                ### ДОДАТКОВІ ВІДОМОСТІ
                
                ПРАВИЛА:
                - ЗАМІСТЬ ТАБЛИЦЬ пиши: **Параметр** — Значення.
                - Текст має бути структурованим, без зайвих коментарів.
                - Якщо дані повторюються на різних скріншотах, обери найповніший варіант."""},
                {"role": "user", "content": f"НАЗВА: {title}\n\nТЕКСТ:\n{raw_text[:15000]}"}
            ], temperature=0
        )
        
        final_text = res.choices[0].message.content

        # Зберігаємо в DOCX
        doc = docx.Document()
        for line in final_text.split('\n'):
            if line.startswith('###'):
                doc.add_heading(line.replace('###', '').strip(), level=3)
            else:
                doc_out_para = doc.add_paragraph(line)
        
        doc.save(res_path)
        with open(res_path, "rb") as f:
            bot.send_document(chat_id, f, caption=f"✅ Оцифровано: {title}")

    except Exception as e:
        bot.send_message(chat_id, f"⚠️ Помилка AI: {e}")
    finally:
        if os.path.exists(res_path): os.remove(res_path)
        user_data_buffer.pop(chat_id, None)
        gc.collect()

# --- 5. ОБРОБНИКИ ---

@bot.message_handler(content_types=['photo'])
def handle_multi_photo(message):
    chat_id = message.chat.id
    
    # Створюємо запис у буфері, якщо його немає
    if chat_id not in user_data_buffer:
        user_data_buffer[chat_id] = {"text": "", "timer": None, "caption": message.caption}
        bot.send_chat_action(chat_id, 'typing')

    # Отримуємо фото та зчитуємо текст
    file_info = bot.get_file(message.photo[-1].file_id)
    temp_img = f"tmp_{chat_id}_{time.time()}.png"
    
    with open(temp_img, "wb") as f:
        f.write(bot.download_file(file_info.file_path))
    
    scanned_text = fast_ocr(temp_img)
    user_data_buffer[chat_id]["text"] += f"\n{scanned_text}"
    
    if os.path.exists(temp_img): os.remove(temp_img)

    # Перезапускаємо таймер очікування (чекаємо 5 секунд після останнього фото)
    if user_data_buffer[chat_id]["timer"]:
        user_data_buffer[chat_id]["timer"].cancel()
    
    t = threading.Timer(5.0, process_combined_data, args=[chat_id])
    user_data_buffer[chat_id]["timer"] = t
    t.start()

@bot.message_handler(content_types=['document'])
def handle_doc(message):
    # Для PDF залишаємо миттєву обробку
    status = bot.reply_to(message, "📄 Зчитую документ...")
    temp_doc = f"doc_{message.chat.id}"
    try:
        file_info = bot.get_file(message.document.file_id)
        with open(temp_doc, "wb") as f:
            f.write(bot.download_file(file_info.file_path))
        
        text = ""
        with fitz.open(temp_doc) as doc:
            for page in doc: text += page.get_text()
        
        # Викликаємо оцифрування відразу
        user_data_buffer[message.chat.id] = {"text": text, "caption": message.caption, "timer": None}
        process_combined_data(message.chat.id)
    finally:
        if os.path.exists(temp_doc): os.remove(temp_doc)
        bot.delete_message(message.chat.id, status.message_id)

# --- 6. ЗАПУСК ---
if __name__ == "__main__":
    threading.Thread(target=run_web, daemon=True).start()
    bot.remove_webhook()
    time.sleep(1)
    print("Бот готовий до пакетної обробки!")
    bot.infinity_polling(timeout=90)
        
