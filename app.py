import os, time, threading, telebot, fitz, docx
from openai import OpenAI
from io import BytesIO
from flask import Flask

web_app = Flask(__name__)
@web_app.route('/')
def health_check(): return "Bot is filtering", 200

def run_web():
    port = int(os.environ.get("PORT", 10000))
    web_app.run(host="0.0.0.0", port=port)

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
AI_KEY = os.environ.get("OPENAI_API_KEY")
bot = telebot.TeleBot(TOKEN)
client = OpenAI(api_key=AI_KEY)

# Словник для збереження інструкцій користувачів
user_instructions = {}

def extract_text(file_path, extension):
    text = ""
    try:
        if extension == 'pdf':
            with fitz.open(file_path) as doc:
                text = "".join([page.get_text() for page in doc])
        elif extension == 'docx':
            doc = docx.Document(file_path)
            text = "\n".join([para.text for para in doc.paragraphs])
    except Exception as e: print(f"Error reading: {e}")
    return text

def process_with_filter(chat_id, initial_status_id, raw_text, user_query):
    step = 5000 # Можна навіть трохи більше, бо відповіді будуть коротші
    chunks = [raw_text[i:i+step] for i in range(0, len(raw_text), step)]
    total = len(chunks)
    current_status_id = initial_status_id
    output_filename = f"filtered_{chat_id}.txt"

    with open(output_filename, "w", encoding="utf-8") as f: f.write(f"РЕЗУЛЬТАТ ЗА ЗАПИТОМ: {user_query}\n" + "="*30 + "\n\n")

    for idx, chunk in enumerate(chunks, 1):
        try:
            bot.delete_message(chat_id, current_status_id)
            new_msg = bot.send_message(chat_id, f"🔍 Шукаю інформацію... Частина {idx}/{total}\nЗапит: {user_query}")
            current_status_id = new_msg.message_id
        except: pass

        try:
            # Спеціальний промпт для фільтрації
            res = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": f"Ти аналітик. Твоє завдання: знайти в тексті ТІЛЬКИ інформацію, що стосується запиту користувача: '{user_query}'. Якщо в частині тексту немає нічого релевантного, просто напиши 'Пропущено'. Використовуй LaTeX для формул."},
                    {"role": "user", "content": chunk}
                ],
                temperature=0.1 # Мінімальна температура для точності
            )
            ans = res.choices[0].message.content
            if "Пропущено" not in ans:
                with open(output_filename, "a", encoding="utf-8") as f:
                    f.write(ans + "\n\n" + "-"*20 + "\n")
        except Exception as e:
            print(f"AI Error: {e}")
        
        time.sleep(1)
            
    return output_filename, current_status_id

@bot.message_handler(commands=['start'])
def welcome(message):
    bot.reply_to(message, "🫡 Бот-аналітик готовий! \n\n**Як працювати:**\nНадішліть файл і в полі 'Підпис' (Caption) напишіть, що саме ви шукаєте (наприклад: 'Випиши всі ТТХ танків' або 'Знайди обов'язки командира взводу').")

@bot.message_handler(content_types=['document'])
def handle_file(message):
    # Беремо запит із підпису до файлу, або ставимо дефолтний
    query = message.caption if message.caption else "Зроби загальну базу знань"
    
    ext = message.document.file_name.split('.')[-1].lower()
    temp_path = f"raw_{message.chat.id}.tmp"
    if ext not in ['pdf', 'docx']: return

    status = bot.reply_to(message, f"📥 Файл прийнято. Шукаю інформацію за запитом: '{query}'...")
    
    try:
        file_info = bot.get_file(message.document.file_id)
        with open(temp_path, "wb") as f:
            f.write(bot.download_file(file_info.file_path))

        text = extract_text(temp_path, ext)
        if os.path.exists(temp_path): os.remove(temp_path)

        if not text.strip():
            bot.edit_message_text("❌ Файл порожній або не зчитався.", message.chat.id, status.message_id)
            return

        res_file, final_status_id = process_with_filter(message.chat.id, status.message_id, text, query)

        if os.path.exists(res_file) and os.path.getsize(res_file) > 100:
            with open(res_file, "rb") as f:
                bot.send_document(message.chat.id, f, caption=f"✅ Аналіз завершено за запитом: {query}")
        else:
            bot.send_message(message.chat.id, "🤷‍♂️ Нічого релевантного за вашим запитом не знайдено.")
        
        if os.path.exists(res_file): os.remove(res_file)
        try: bot.delete_message(message.chat.id, final_status_id)
        except: pass

    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Помилка: {e}")

if __name__ == "__main__":
    threading.Thread(target=run_web, daemon=True).start()
    bot.infinity_polling(timeout=90)
