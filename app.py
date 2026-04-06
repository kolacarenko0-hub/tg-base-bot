import os, time, threading, telebot, fitz, re, gc
from openai import OpenAI
from flask import Flask
from PIL import Image
import pytesseract

web_app = Flask(__name__)
@web_app.route('/')
def health_check(): return "Stream OCR Active", 200

def run_web():
    port = int(os.environ.get("PORT", 10000))
    web_app.run(host="0.0.0.0", port=port)

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
AI_KEY = os.environ.get("OPENAI_API_KEY")
bot = telebot.TeleBot(TOKEN)
client = OpenAI(api_key=AI_KEY)

def get_text_optimized(page):
    """Обробка однієї сторінки з мінімальним споживанням RAM"""
    text = page.get_text().strip()
    if len(text) < 20:
        # Зменшуємо розширення для OCR (2.0 замість 3.0), щоб зекономити пам'ять
        pix = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5)) 
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        text = pytesseract.image_to_string(img, lang='ukr+eng')
        # Явно видаляємо важкі об'єкти з пам'яті
        del pix
        del img
    return text

def process_stream(chat_id, status_id, file_path, query, start_idx, end_idx):
    # Відкриваємо файл у режимі стриму (не завантажуємо весь в RAM)
    doc = fitz.open(file_path)
    output_file = f"result_{chat_id}.txt"
    current_status_id = status_id

    with open(output_file, "w", encoding="utf-8") as f:
        f.write(f"📊 ЗВІТ ПО СТОРІНКАХ {start_idx+1}-{end_idx}\nЗАПИТ: {query}\n\n")

    for i in range(start_idx, end_idx):
        try:
            bot.delete_message(chat_id, current_status_id)
            msg = bot.send_message(chat_id, f"📖 Опрацьовано {i+1-start_idx} з {end_idx-start_idx} сторінок...")
            current_status_id = msg.message_id
        except: pass

        page_text = get_text_optimized(doc[i])
        
        if page_text.strip():
            try:
                res = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {"role": "system", "content": f"Ти військовий аналітик. Витягни суть за запитом: '{query}'."},
                        {"role": "user", "content": page_text}
                    ], temperature=0.1
                )
                with open(output_file, "a", encoding="utf-8") as f:
                    f.write(f"\n--- СТОРІНКА {i+1} ---\n{res.choices[0].message.content}\n")
            except: pass

        # Примусове очищення "сміття" в пам'яті після кожної сторінки
        gc.collect() 
        time.sleep(0.5)

    doc.close()
    return output_file, current_status_id

@bot.message_handler(content_types=['document'])
def handle_docs(message):
    if not message.document.file_name.lower().endswith('.pdf'):
        bot.reply_to(message, "❌ Будь ласка, надсилай PDF.")
        return

    status = bot.reply_to(message, "📥 Отримано великий файл. Готуюся до потокової обробки...")
    temp_path = f"large_{message.chat.id}.pdf"

    try:
        file_info = bot.get_file(message.document.file_id)
        with open(temp_path, "wb") as f:
            f.write(bot.download_file(file_info.file_path))

        doc_info = fitz.open(temp_path)
        total_p = len(doc_info)
        doc_info.close()

        # Парсимо діапазон сторінок
        match = re.search(r'(\d+)\s*-\s*(\d+)', str(message.caption))
        if match:
            start_idx = max(0, int(match.group(1)) - 1)
            end_idx = min(total_p, int(match.group(2)))
        else:
            # Якщо діапазон не вказано, беремо перші 5 сторінок (безпечний ліміт)
            start_idx, end_idx = 0, min(total_p, 5)
            bot.send_message(message.chat.id, "⚠️ Діапазон не вказано. Обробляю перші 5 сторінок. Для більшого пиши, напр., '10-30'.")

        query = re.sub(r'\d+\s*-\s*\d+', '', message.caption or "Аналіз").strip()

        res_path, last_status = process_stream(message.chat.id, status.message_id, temp_path, query, start_idx, end_idx)

        with open(res_path, "rb") as f:
            bot.send_document(message.chat.id, f, caption=f"✅ Готово! Стор. {start_idx+1}-{end_idx}")

        if os.path.exists(temp_path): os.remove(temp_path)
        if os.path.exists(res_path): os.remove(res_path)
        bot.delete_message(message.chat.id, last_status)

    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Помилка пам'яті: {e}")

if __name__ == "__main__":
    threading.Thread(target=run_web, daemon=True).start()
    bot.infinity_polling(timeout=90)
    
