import os
import time
import threading
import re
import gc
import telebot
import fitz  # PyMuPDF
from openai import OpenAI
from flask import Flask
from PIL import Image
import pytesseract

# --- 1. ВЕБ-СЕРВЕР ДЛЯ RENDER ---
web_app = Flask(__name__)
@web_app.route('/')
def health_check(): return "Ultra-Light OCR Active", 200

def run_web():
    port = int(os.environ.get("PORT", 10000))
    web_app.run(host="0.0.0.0", port=port)

# --- 2. НАЛАШТУВАННЯ ---
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
AI_KEY = os.environ.get("OPENAI_API_KEY")

bot = telebot.TeleBot(TOKEN)
client = OpenAI(api_key=AI_KEY)

# --- 3. ОПТИМІЗОВАНА ФУНКЦІЯ ОБРОБКИ СТОРІНКИ ---
def get_text_ultra_light(page_index, file_path):
    """Відкриває ОДНУ сторінку, розпізнає її та миттєво звільняє RAM"""
    text = ""
    try:
        doc = fitz.open(file_path)
        page = doc[page_index]
        
        # Спробуємо витягти готовий текст
        text = page.get_text().strip()
        
        # Якщо тексту немає (скан) - запускаємо економний OCR
        if len(text) < 25:
            # Matrix(1.2) + GRAY - це мінімальне споживання пам'яті
            pix = page.get_pixmap(matrix=fitz.Matrix(1.2, 1.2), colorspace=fitz.csGRAY)
            img = Image.frombytes("L", [pix.width, pix.height], pix.samples)
            
            text = pytesseract.image_to_string(img, lang='ukr+eng')
            
            # Очищення важких об'єктів картинки
            del pix
            del img
        
        doc.close()
    except Exception as e:
        print(f"Помилка на сторінці {page_index}: {e}")
    
    gc.collect() # Примусове очищення сміття в RAM
    return text

# --- 4. ГОЛОВНИЙ ЦИКЛ ОБРОБКИ ---
def process_document_stream(chat_id, status_id, file_path, query, start_idx, end_idx):
    output_filename = f"report_{chat_id}.txt"
    current_status_id = status_id

    with open(output_filename, "w", encoding="utf-8") as f:
        f.write(f"📊 ЗВІТ (ULTRA-LIGHT MODE)\nЗапит: {query}\nСторінки: {start_idx+1}-{end_idx}\n" + "="*30 + "\n")

    for i in range(start_idx, end_idx):
        # Оновлюємо статус раз на 2 сторінки, щоб не перевантажувати бота
        if i % 2 == 0 or i == start_idx:
            try:
                bot.edit_message_text(f"📖 Обробка: {i+1} з {end_idx}...", chat_id, current_status_id)
            except: pass

        # Отримуємо текст сторінки
        content = get_text_ultra_light(i, file_path)
        
        if content.strip():
            try:
                # Запит до AI (gpt-4o-mini найшвидша і найдешевша)
                res = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {"role": "system", "content": "Ти військовий аналітик. Коротко випиши головні тези, цифри та назви за запитом."},
                        {"role": "user", "content": f"Запит: {query}\n\nТекст сторінки:\n{content[:3500]}"}
                    ],
                    temperature=0.1
                )
                
                # Дописуємо у файл (не тримаємо весь звіт у пам'яті)
                with open(output_filename, "a", encoding="utf-8") as f:
                    f.write(f"\n[Стор. {i+1}]\n{res.choices[0].message.content}\n")
            except Exception as ai_e:
                print(f"AI Error: {ai_e}")

        # Пауза між сторінками для розвантаження процесора
        time.sleep(0.8)
        gc.collect()

    return output_filename, current_status_id

# --- 5. ОБРОБНИКИ ТЕЛЕГРАМ ---
@bot.message_handler(content_types=['document'])
def handle_pdf(message):
    if not message.document.file_name.lower().endswith('.pdf'):
        bot.reply_to(message, "❌ Надішліть, будь ласка, файл у форматі PDF.")
        return

    status = bot.reply_to(message, "⏳ Починаю енергоефективну обробку...")
    temp_path = f"file_{message.chat.id}.pdf"
    
    try:
        # Завантажуємо файл
        file_info = bot.get_file(message.document.file_id)
        with open(temp_path, "wb") as f:
            f.write(bot.download_file(file_info.file_path))

        # Визначаємо діапазон сторінок
        doc = fitz.open(temp_path)
        total_p = len(doc)
        doc.close()

        match = re.search(r'(\d+)\s*-\s*(\d+)', str(message.caption))
        if match:
            start_idx = max(0, int(match.group(1)) - 1)
            end_idx = min(total_p, int(match.group(2)))
        else:
            # Безпечний ліміт за замовчуванням
            start_idx, end_idx = 0, min(total_p, 3)
            bot.send_message(message.chat.id, "ℹ️ Діапазон не вказано. Обробляю перші 3 сторінки. Наприклад: '5-15'")

        query = re.sub(r'\d+\s*-\s*\d+', '', message.caption or "Головні тези").strip()

        # Запускаємо стрім-обробку
        final_file, last_status_id = process_document_stream(message.chat.id, status.message_id, temp_path, query, start_idx, end_idx)

        # Відправка результату
        with open(final_file, "rb") as f:
            bot.send_document(message.chat.id, f, caption=f"✅ Готово! Оброблено {end_idx-start_idx} стор.")

        # Очищення
        for path in [temp_path, final_file]:
            if os.path.exists(path): os.remove(path)
        
        try: bot.delete_message(message.chat.id, last_status_id)
        except: pass

    except Exception as e:
        bot.send_message(message.chat.id, f"⚠️ Виникла помилка (можливо, файл занадто важкий): {e}")

# --- 6. ЗАПУСК ---
if __name__ == "__main__":
    threading.Thread(target=run_web, daemon=True).start()
    bot.infinity_polling(timeout=90, long_polling_timeout=60)
        
