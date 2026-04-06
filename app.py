import os, time, threading, telebot, fitz, docx, re
from openai import OpenAI
from flask import Flask

web_app = Flask(__name__)
@web_app.route('/')
def health_check(): return "Smart Pagination Active", 200

def run_web():
    port = int(os.environ.get("PORT", 10000))
    web_app.run(host="0.0.0.0", port=port)

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
AI_KEY = os.environ.get("OPENAI_API_KEY")
bot = telebot.TeleBot(TOKEN)
client = OpenAI(api_key=AI_KEY)

def get_real_page_map(doc):
    """Створює словник: {друкований_номер: індекс_у_файлі}"""
    page_map = {}
    for i in range(len(doc)):
        # Беремо текст тільки з верхньої та нижньої частин сторінки (по 10% висоти)
        rect = doc[i].rect
        footer_rect = fitz.Rect(0, rect.height * 0.85, rect.width, rect.height)
        header_rect = fitz.Rect(0, 0, rect.width, rect.height * 0.15)
        
        edge_text = doc[i].get_text("text", clip=footer_rect) + doc[i].get_text("text", clip=header_rect)
        
        # Шукаємо окремі числа у знайденому тексті
        numbers = re.findall(r'\b\d+\b', edge_text)
        if numbers:
            # Беремо останнє число (зазвичай номер сторінки внизу)
            real_num = int(numbers[-1])
            if real_num not in page_map: # Щоб не перезаписувати, якщо номер дублюється
                page_map[real_num] = i
    return page_map

def parse_smart_range(caption, page_map, total_physical):
    """Визначає старт і кінець на основі карти сторінок або фізичного обсягу"""
    match = re.search(r'(\d+)\s*-\s*(\d+)', str(caption))
    if not match:
        return 0, total_physical

    req_start = int(match.group(1))
    req_end = int(match.group(2))

    # Якщо ми знайшли ці номери в документі через карту
    start_idx = page_map.get(req_start, -1)
    end_idx = page_map.get(req_end, -1)

    # Якщо карта не допомогла (немає номерів), працюємо по фізичних
    if start_idx == -1: start_idx = max(0, req_start - 1)
    if end_idx == -1: end_idx = min(total_physical, req_end)
    else: end_idx += 1 # Включаємо сторінку з номером кінця

    return start_idx, end_idx

def process_with_ai(chat_id, status_id, doc_path, query, start_idx, end_idx):
    doc = fitz.open(doc_path)
    output_text = f"📄 ОБРОБКА (ЗМІСТОВНІ СТОРІНКИ): {start_idx+1} - {end_idx}\n"
    current_status_id = status_id

    for i in range(start_idx, end_idx):
        try:
            bot.delete_message(chat_id, current_status_id)
            msg = bot.send_message(chat_id, f"📖 Аналізую сторінку {i+1}...")
            current_status_id = msg.message_id
        except: pass

        text = doc[i].get_text()
        if not text.strip(): continue

        try:
            res = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": f"Ти військовий аналітик. Витягни дані за запитом: '{query}'. Використовуй LaTeX для формул."},
                    {"role": "user", "content": text}
                ], temperature=0.1
            )
            output_text += f"\n--- Стор. {i+1} ---\n{res.choices[0].message.content}\n"
        except: pass
        time.sleep(1)
    
    doc.close()
    return output_text, current_status_id

@bot.message_handler(content_types=['document'])
def handle_file(message):
    ext = message.document.file_name.split('.')[-1].lower()
    if ext != 'pdf':
        bot.reply_to(message, "❌ Розумна нумерація поки що тільки для PDF.")
        return

    status = bot.reply_to(message, "📥 Завантаження та індексація змісту...")
    temp_path = f"file_{message.chat.id}.pdf"
    
    try:
        file_info = bot.get_file(message.document.file_id)
        with open(temp_path, "wb") as f:
            f.write(bot.download_file(file_info.file_path))

        doc = fitz.open(temp_path)
        # Крок 1: Скануємо номери сторінок у самому документі
        page_map = get_real_page_map(doc)
        total_p = len(doc)
        doc.close()

        # Крок 2: Визначаємо діапазон
        start_idx, end_idx = parse_smart_range(message.caption, page_map, total_p)
        query = re.sub(r'\d+\s*-\s*\d+', '', message.caption or "База знань").strip()

        # Крок 3: Обробка
        final_text, last_status_id = process_with_ai(message.chat.id, status.message_id, temp_path, query, start_idx, end_idx)

        res_file = f"res_{message.chat.id}.txt"
        with open(res_file, "w", encoding="utf-8") as f: f.write(final_text)
        with open(res_file, "rb") as f:
            bot.send_document(message.chat.id, f, caption=f"✅ Аналіз завершено (діапазон знайдено)")

        os.remove(res_file)
        os.remove(temp_path)
        bot.delete_message(message.chat.id, last_status_id)

    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Помилка: {e}")

if __name__ == "__main__":
    threading.Thread(target=run_web, daemon=True).start()
    bot.infinity_polling(timeout=90)
        
