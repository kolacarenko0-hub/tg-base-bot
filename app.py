import os, time, threading, telebot, fitz, docx, re
from openai import OpenAI
from flask import Flask
from PIL import Image
import pytesseract

# Налаштування для OCR (на Render шлях зазвичай такий, на Windows треба вказувати шлях до .exe)
# pytesseract.pytesseract.tesseract_cmd = r'/usr/bin/tesseract' 

web_app = Flask(__name__)
@web_app.route('/')
def health_check(): return "OCR Mode Active", 200

def run_web():
    port = int(os.environ.get("PORT", 10000))
    web_app.run(host="0.0.0.0", port=port)

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
AI_KEY = os.environ.get("OPENAI_API_KEY")
bot = telebot.TeleBot(TOKEN)
client = OpenAI(api_key=AI_KEY)

def get_text_with_ocr(page):
    """Спробує взяти текст, якщо порожньо — робить OCR сторінки"""
    text = page.get_text().strip()
    if len(text) < 10: # Якщо тексту майже немає, вважаємо це сканом
        # Перетворюємо сторінку в картинку (300 DPI для кращої якості)
        pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        # Розпізнаємо текст (мова: українська + англійська)
        text = pytesseract.image_to_string(img, lang='ukr+eng')
    return text

def parse_smart_range(caption, total_physical):
    match = re.search(r'(\d+)\s*-\s*(\d+)', str(caption))
    if not match: return 0, total_physical
    return max(0, int(match.group(1)) - 1), min(total_physical, int(match.group(2)))

@bot.message_handler(content_types=['document'])
def handle_file(message):
    ext = message.document.file_name.split('.')[-1].lower()
    if ext != 'pdf':
        bot.reply_to(message, "❌ OCR наразі оптимізовано під PDF скани.")
        return

    status = bot.reply_to(message, "🔍 Завантаження та підготовка до OCR (це може зайняти час)...")
    temp_path = f"ocr_{message.chat.id}.pdf"
    
    try:
        file_info = bot.get_file(message.document.file_id)
        with open(temp_path, "wb") as f:
            f.write(bot.download_file(file_info.file_path))

        doc = fitz.open(temp_path)
        total_p = len(doc)
        start_idx, end_idx = parse_smart_range(message.caption, total_p)
        query = re.sub(r'\d+\s*-\s*\d+', '', message.caption or "Аналіз").strip()

        final_text = f"📄 ЗВІТ (OCR MODE)\nДіапазон: {start_idx+1}-{end_idx}\n" + "="*20 + "\n"
        current_status_id = status.message_id

        for i in range(start_idx, end_idx):
            try:
                bot.delete_message(message.chat.id, current_status_id)
                msg = bot.send_message(message.chat.id, f"👁 Сканую сторінку {i+1}...")
                current_status_id = msg.message_id
            except: pass

            # ОСНОВНА ФІШКА: Витягуємо текст навіть зі скану
            page_text = get_text_with_ocr(doc[i])
            
            if not page_text.strip(): continue

            res = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": f"Ти військовий аналітик. Опрацюй текст за запитом: '{query}'. Використовуй LaTeX."},
                    {"role": "user", "content": page_text}
                ], temperature=0.1
            )
            final_text += f"\n--- Стор. {i+1} ---\n{res.choices[0].message.content}\n"
            time.sleep(1)

        doc.close()
        res_file = f"res_{message.chat.id}.txt"
        with open(res_file, "w", encoding="utf-8") as f: f.write(final_text)
        with open(res_file, "rb") as f:
            bot.send_document(message.chat.id, f, caption="✅ Аналіз сканів завершено!")

        os.remove(res_file)
        os.remove(temp_path)
        bot.delete_message(message.chat.id, current_status_id)

    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Помилка: {e}")

if __name__ == "__main__":
    threading.Thread(target=run_web, daemon=True).start()
    bot.infinity_polling(timeout=90)
        
