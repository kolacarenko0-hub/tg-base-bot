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

# --- 1. ВЕБ-СЕРВЕР ДЛЯ ПІДТРИМКИ ЖИТТЄДІЯЛЬНОСТІ НА RENDER ---
web_app = Flask(__name__)
@web_app.route('/')
def health_check(): return "Smart Queue OCR Active", 200

def run_web():
    port = int(os.environ.get("PORT", 10000))
    web_app.run(host="0.0.0.0", port=port)

# --- 2. КОНФІГУРАЦІЯ ---
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
AI_KEY = os.environ.get("OPENAI_API_KEY")

bot = telebot.TeleBot(TOKEN)
client = OpenAI(api_key=AI_KEY)

# Налаштування лімітів для безкоштовного Render (512MB RAM)
CHUNK_SIZE = 7  # Обробити по 7 сторінок за один підхід

# --- 3. ОПТИМІЗОВАНЕ ЗЧИТУВАННЯ СТОРІНКИ ---
def get_text_ultra_light(page_index, file_path):
    """Ізольоване відкриття однієї сторінки для економії RAM"""
    text = ""
    try:
        doc = fitz.open(file_path)
        page = doc[page_index]
        text = page.get_text().strip()
        
        # Якщо тексту немає або це скан - вмикаємо економний OCR (чорно-білий)
        if len(text) < 25:
            # Масштаб 1.2 та сіра палітра споживають мінімум пам'яті
            pix = page.get_pixmap(matrix=fitz.Matrix(1.2, 1.2), colorspace=fitz.csGRAY)
            img = Image.frombytes("L", [pix.width, pix.height], pix.samples)
            text = pytesseract.image_to_string(img, lang='ukr+eng')
            del pix
            del img
        
        doc.close()
    except Exception as e:
        print(f"Помилка на сторінці {page_index}: {e}")
    
    gc.collect() # Примусовий збір сміття
    return text

# --- 4. РОЗУМНА ОБРОБКА ДІАПАЗОНУ (ЧЕРГА) ---
def process_smart_chunks(chat_id, status_id, file_path, query, start_idx, end_idx):
    output_filename = f"analysis_{chat_id}.txt"
    current_status_id = status_id

    with open(output_filename, "w", encoding="utf-8") as f:
        f.write(f"📋 ЗВІТ АНАЛІТИКА (ЧЕРГОВА ОБРОБКА)\nЗапит: {query}\nДіапазон: {start_idx+1}-{end_idx}\n" + "="*35 + "\n")

    # Розбиваємо великий запит на безпечні частини (Chunks)
    for chunk_start in range(start_idx, end_idx, CHUNK_SIZE):
        chunk_end = min(chunk_start + CHUNK_SIZE, end_idx)
        
        try:
            bot.edit_message_text(
                f"⏳ Обробка пакета сторінок: {chunk_start+1}-{chunk_end} з {end_idx}...", 
                chat_id, current_status_id
            )
        except: pass

        # Обробка сторінок всередині пакета
        for i in range(chunk_start, chunk_end):
            content = get_text_ultra_light(i, file_path)
            
            if content.strip():
                try:
                    res = client.chat.completions.create(
                        model="gpt-4o-mini",
                        messages=[
                            {"role": "system", "content": "Ти військовий аналітик. Коротко випиши головні тези та цифри за запитом."},
                            {"role": "user", "content": f"Запит: {query}\n\nТекст сторінки:\n{content[:3500]}"}
                        ],
                        temperature=0.1
                    )
                    with open(output_filename, "a", encoding="utf-8") as f:
                        f.write(f"\n[Стор. {i+1}]\n{res.choices[0].message.content}\n")
                except Exception as ai_e:
                    print(f"AI Error: {ai_e}")

            # Короткий "відпочинок" для RAM після кожної сторінки
            gc.collect()
            time.sleep(0.5)

        # Пауза між пакетами сторінок (chunks)
        time.sleep(2) 
        gc.collect()

    return output_filename, current_status_id

# --- 5. ОБРОБНИКИ ПОВІДОМЛЕНЬ ---
@bot.message_handler(content_types=['document'])
def handle_pdf(message):
    if not message.document.file_name.lower().endswith('.pdf'):
        bot.reply_to(message, "❌ Потрібен файл у форматі PDF.")
        return

    status = bot.reply_to(message, "📥 Файл отримано. Розраховую чергу обробки...")
    temp_path = f"doc_{message.chat.id}.pdf"
    
    try:
        # Завантаження
        file_info = bot.get_file(message.document.file_id)
        with open(temp_path, "wb") as f:
            f.write(bot.download_file(file_info.file_path))

        # Визначаємо межі
        doc = fitz.open(temp_path)
        total_p = len(doc)
        doc.close()

        caption = message.caption if message.caption else ""
        match = re.search(r'(\d+)\s*-\s*(\d+)', caption)
        
        if match:
            start_idx = max(0, int(match.group(1)) - 1)
            end_idx = min(total_p, int(match.group(2)))
        else:
            start_idx, end_idx = 0, min(total_p, 5)
            bot.send_message(message.chat.id, "⚠️ Діапазон не вказано. Роблю перші 5 сторінок. Для більшого пиши '1-20'.")

        query = re.sub(r'\d+\s*-\s*\d+', '', caption).strip()
        if not query: query = "Загальний аналіз змісту"

        # Запуск черги
        final_file, last_status_id = process_smart_chunks(message.chat.id, status.message_id, temp_path, query, start_idx, end_idx)

        # Надсилання результату
        with open(final_file, "rb") as f:
            bot.send_document(message.chat.id, f, caption=f"✅ Обробка сторінок {start_idx+1}-{end_idx} завершена успішно.")

        # Очищення файлів
        for p in [temp_path, final_file]:
            if os.path.exists(p): os.remove(p)
        
        try: bot.delete_message(message.chat.id, last_status_id)
        except: pass

    except Exception as e:
        bot.send_message(message.chat.id, f"⚠️ Помилка обробки: {e}\nСпробуйте менший діапазон сторінок.")
        if os.path.exists(temp_path): os.remove(temp_path)

# --- 6. ЗАПУСК ---
if __name__ == "__main__":
    threading.Thread(target=run_web, daemon=True).start()
    bot.infinity_polling(timeout=90, long_polling_timeout=60)
            
