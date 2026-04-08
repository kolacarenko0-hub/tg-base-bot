import os
import time
import threading
import telebot
import re
import io
import base64
from openai import OpenAI
from flask import Flask
from docx import Document
from PIL import Image

# --- 1. ВЕБ-СЕРВЕР ---
web_app = Flask(__name__)
@web_app.route('/')
def health_check(): return "Ready", 200

def run_web():
    port = int(os.environ.get("PORT", 10000))
    web_app.run(host="0.0.0.0", port=port)

# --- 2. КОНФІГУРАЦІЯ ---
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
AI_KEY = os.environ.get("OPENAI_API_KEY")
# Сюди все ж таки краще вписати свій ID, щоб бот знав, у який чат звітувати
MY_ID = "ТВІЙ_ТЕЛЕГРАМ_ID" 

bot = telebot.TeleBot(TOKEN)
client = OpenAI(api_key=AI_KEY)

user_sessions = {}
sessions_lock = threading.Lock()

# --- 3. ЛОГІКА (ФРАГМЕНТАЦІЯ + КОРЕКТУРА) ---
def process_fragmented_data(chat_id):
    with sessions_lock:
        session = user_sessions.get(chat_id)
        if not session: return
        image_data_list = session['images']

    try:
        raw_text = ""
        for img_bytes in image_data_list:
            img = Image.open(io.BytesIO(img_bytes))
            w, h = img.size
            overlap = 150
            ph = h // 3
            coords = [(0, 0, w, ph + overlap), (0, ph, w, 2 * ph + overlap), (0, 2 * ph, w, h)]
            
            for box in coords:
                fragment = img.crop(box)
                buf = io.BytesIO()
                fragment.save(buf, format="JPEG")
                img_b64 = base64.b64encode(buf.getvalue()).decode('utf-8')

                try:
                    res = client.chat.completions.create(
                        model="gpt-4o-mini",
                        messages=[{"role": "user", "content": [
                            {"type": "text", "text": "ПЕРЕПИШИ ТЕКСТ ДОСЛІВНО. Тільки OCR."},
                            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}", "detail": "high"}}
                        ]}],
                        temperature=0
                    )
                    raw_text += res.choices[0].message.content + "\n"
                    time.sleep(1.5)
                except: time.sleep(5)

        # Коректура
        fix = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": f"Ти технічний редактор. Виправ помилки OCR, видали дублікати, збережи структуру ###. Не скорочуй:\n\n{raw_text}"}]
        )
        final_text = fix.choices[0].message.content

        # Word
        doc = Document()
        for line in final_text.split('\n'):
            line = line.strip()
            if not line: continue
            if line.startswith('###'):
                doc.add_heading(line.replace('###', '').strip(), level=1)
            else:
                doc.add_paragraph(line)

        path = f"doc_{chat_id}.docx"
        doc.save(path)
        with open(path, "rb") as f:
            bot.send_document(chat_id, f, caption="✅ Готово")
        os.remove(path)

    except Exception as e:
        bot.send_message(chat_id, f"❌ Помилка: {e}")
    finally:
        with sessions_lock: user_sessions.pop(chat_id, None)

# --- 4. ОБРОБНИКИ ---
@bot.message_handler(content_types=['photo'])
def handle_photos(message):
    cid = message.chat.id
    info = bot.get_file(message.photo[-1].file_id)
    img = bot.download_file(info.file_path)

    with sessions_lock:
        if cid not in user_sessions:
            user_sessions[cid] = {'images': [], 'timer': None}
            bot.send_message(cid, "⚙️ Обробка...")
        user_sessions[cid]['images'].append(img)
        if user_sessions[cid]['timer']: user_sessions[cid]['timer'].cancel()
        t = threading.Timer(12.0, process_fragmented_data, args=[cid])
        user_sessions[cid]['timer'] = t
        t.start()

# --- 5. СТАРТ ---
if __name__ == "__main__":
    threading.Thread(target=run_web, daemon=True).start()
    bot.remove_webhook()
    
    # Повідомлення в чат бота
    if MY_ID and MY_ID != "ТВІЙ_ТЕЛЕГРАМ_ID":
        try:
            bot.send_message(MY_ID, "🚀 Бот онлайн")
        except: pass

    bot.infinity_polling(timeout=90)
