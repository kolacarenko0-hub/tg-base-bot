import os
import time
import telebot
import fitz
import docx
from openai import OpenAI
from io import BytesIO
from telebot import apihelper

# --- 1. НАЛАШТУВАННЯ ---
apihelper.CONNECT_TIMEOUT = 40
apihelper.READ_TIMEOUT = 40

OPENAI_KEY = os.environ.get("OPENAI_API_KEY")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")

if not TELEGRAM_TOKEN or not OPENAI_KEY:
    print("❌ Помилка: Ключі не знайдено!")
    exit(1)

client = OpenAI(api_key=OPENAI_KEY)
bot = telebot.TeleBot(TELEGRAM_TOKEN)

# --- 2. СКРИПТИ ЗЧИТУВАННЯ ---
def extract_text(file_path, extension):
    text = ""
    try:
        if extension == 'pdf':
            with fitz.open(file_path) as doc:
                text = "".join([page.get_text() for page in doc])
        elif extension == 'docx':
            doc = docx.Document(file_path)
            text = "\n".join([para.text for para in doc.paragraphs])
    except Exception as e:
        print(f"Помилка зчитування: {e}")
    return text

# --- 3. AI ОБРОБКА ---
def process_with_progress(chat_id, status_msg_id, raw_text):
    all_results = []
    step = 5000 
    chunks = [raw_text[i:i+step] for i in range(0, len(raw_text), step)]
    total = len(chunks)
    
    for idx, chunk in enumerate(chunks, 1):
        progress = int((idx / total) * 100)
        try:
            bot.edit_message_text(
                f"🧠 Обробка: {progress}% [{idx}/{total}]",
                chat_id, 
                status_msg_id
            )
        except:
            pass

        prompt = f"Ти техредактор. Зроби базу знань. Структура: ### [НАЗВА]. Формули: LaTeX. Текст: {chunk}"

        try:
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2
            )
            all_results.append(response.choices[0].message.content)
        except Exception as e:
            all_results.append(f"\n[Помилка частини {idx}]\n")
            
    return "\n\n".join(all_results)

# --- 4. ОБРОБНИКИ TELEGRAM ---
@bot.message_handler(commands=['start'])
def start_command(message):
    bot.reply_to(message, "🫡 Бот готовий! Кидай PDF або DOCX.")

@bot.message_handler(content_types=['document'])
def handle_document(message):
    file_name = message.document.file_name
    ext = file_name.split('.')[-1].lower()
    temp_path = f"temp_{message.chat.id}_{int(time.time())}.tmp"
    
    if ext not in ['pdf', 'docx']:
        bot.reply_to(message, "❌ Тільки PDF або DOCX.")
        return

    status_msg = bot.reply_to(message, "📥 Файл отримано...")

    try:
        file_info = bot.get_file(message.document.file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        with open(temp_path, "wb") as f:
            f.write(downloaded_file)

        raw_text = extract_text(temp_path, ext)
        if not raw_text.strip():
            bot.edit_message_text("❌ Файл порожній.", message.chat.id, status_msg.message_id)
            return

        final_text = process_with_progress(message.chat.id, status_msg.message_id, raw_text)

        output = BytesIO()
        output.name = "base.txt"
        output.write(final_text.encode('utf-8'))
        output.seek(0)

        bot.send_document(message.chat.id, output, caption=f"✅ Готово: {file_name}")
        bot.delete_message(message.chat.id, status_msg.message_id)

    except Exception as e:
        bot.reply_to(message, f"❌ Помилка: {e}")
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)

# --- 5. ЗАПУСК ---
if __name__ == "__main__":
    print("🚀 Docker-бот запущений...")
    while True:
        try:
            bot.infinity_polling(timeout=40, long_polling_timeout=20)
        except Exception as e:
            print(f"⚠️ Перепідключення через 15с... ({e})")
            time.sleep(15)