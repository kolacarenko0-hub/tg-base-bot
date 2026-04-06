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
def health_check(): return "Scanner Bot Active", 200

def run_web():
    port = int(os.environ.get("PORT", 10000))
    web_app.run(host="0.0.0.0", port=port)

# --- 2. КОНФІГУРАЦІЯ ---
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
AI_KEY = os.environ.get("OPENAI_API_KEY")
bot = telebot.TeleBot(TOKEN)
client = OpenAI(api_key=AI_KEY)

# --- 3. ФУНКЦІЇ ЗЧИТУВАННЯ ---

def extract_text_from_pdf(path):
    """Витягує текст зі збереженням блочної структури (для таблиць)"""
    text = ""
    try:
        with fitz.open(path) as doc:
            for page in doc:
                # "blocks" краще зберігає структуру колонок та таблиць
                blocks = page.get_text("blocks")
                for b in blocks:
                    text += b[4] + "\n"
                text += "\n" + "-"*20 + "\n"
    except Exception as e:
        print(f"PDF Error: {e}")
    return text

def extract_text_from_img(path):
    """OCR для скріншотів"""
    try:
        img = Image.open(path)
        # Збільшуємо чіткість для таблиць
        text = pytesseract.image_to_string(img, lang='ukr+eng', config='--psm 6') 
        return text
    except:
        return ""

# --- 4. ОБРОБКА ЧЕРЕЗ AI (ФОРМАТУВАННЯ) ---
# --- ОНОВЛЕНА ФУНКЦІЯ ФОРМАТУВАННЯ ---
def format_content(raw_text):
    try:
        res = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": """Ти — професійний диджиталізатор документів. 
                Твоє завдання: перетворити сирий текст на структуровані блоки.
                
                ПРАВИЛА:
                1. Розділяй інформацію на логічні блоки за допомогою заголовків: ### НАЗВА БЛОКУ.
                2. ТАБЛИЦІ: Використовуй суворий Markdown формат (| Column |). 
                   Якщо таблиця складна або дуже широка — перетвори її на список форматі 'Назва поля: Значення'.
                3. СТРУКТУРА: Дотримуйся чіткої ієрархії, щоб дані було легко зчитувати автоматизованим системам.
                4. НІЯКИХ коментарів від себе. Тільки структуровані дані з документа.
                5. Виправляй очевидні помилки розпізнавання символів (OCR артефакти)."""},
                {"role": "user", "content": f"Оцифруй цей текст:\n{raw_text[:12000]}"}
            ],
            temperature=0
        )
        return res.choices[0].message.content
    except Exception as e:
        return f"Помилка оцифрування: {e}"

# --- ОНОВЛЕНИЙ ОБРОБНИК (ЗБЕРЕЖЕННЯ СТРУКТУРИ) ---
@bot.message_handler(content_types=['photo', 'document'])
def handle_files(message):
    status = bot.reply_to(message, "⚙️ Виконую структурне оцифрування...")
    temp_path = f"in_{message.chat.id}"
    res_path = f"struct_{message.chat.id}.docx"
    
    try:
        if message.content_type == 'photo':
            file_info = bot.get_file(message.photo[-1].file_id)
            temp_path += ".png"
            with open(temp_path, "wb") as f:
                f.write(bot.download_file(file_info.file_path))
            # Для таблиць на фото використовуємо спеціальний режим psm 6
            raw_text = pytesseract.image_to_string(Image.open(temp_path), lang='ukr+eng', config='--psm 6')
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
            else: return

        formatted_data = format_content(raw_text)

        # Створюємо документ з підтримкою структури
        doc_out = docx.Document()
        for line in formatted_data.split('\n'):
            if line.startswith('###'):
                doc_out.add_heading(line.replace('###', '').strip(), level=3)
            else:
                doc_out.add_paragraph(line)
        
        doc_out.save(res_path)

        with open(res_path, "rb") as f:
            bot.send_document(message.chat.id, f, caption="✅ Структуровані дані готові для основного бота.")

    except Exception as e:
        bot.reply_to(message, f"❌ Помилка: {e}")
    finally:
        for p in [temp_path, res_path]:
            if os.path.exists(p): os.remove(p)
        bot.delete_message(message.chat.id, status.message_id)
        gc.collect()

# --- 5. ОБРОБНИКИ ---

@bot.message_handler(content_types=['photo', 'document'])
def handle_files(message):
    status = bot.reply_to(message, "📥 Зчитую дані та формую документ...")
    temp_path = f"input_{message.chat.id}"
    res_path = f"result_{message.chat.id}.docx"
    
    try:
        # Завантаження файлу або фото
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
                doc = docx.Document(temp_path)
                raw_text = "\n".join([p.text for p in doc.paragraphs])
            else:
                bot.reply_to(message, "❌ Формат не підтримується.")
                return

        # Форматування через AI
        formatted_text = format_content(raw_text)

        # Створення вихідного DOCX файлу
        output_doc = docx.Document()
        output_doc.add_paragraph(formatted_text)
        output_doc.save(res_path)

        # Відправка результату
        with open(res_path, "rb") as f:
            bot.send_document(message.chat.id, f, caption="✅ Текст оцифровано та збережено у файл.")

    except Exception as e:
        bot.reply_to(message, f"⚠️ Помилка: {e}")
    finally:
        # Очищення
        for p in [temp_path, res_path]:
            if os.path.exists(p): os.remove(p)
        bot.delete_message(message.chat.id, status.message_id)
        gc.collect()

# --- 6. ЗАПУСК ---
if __name__ == "__main__":
    threading.Thread(target=run_web, daemon=True).start()
    bot.remove_webhook()
    time.sleep(1)
    print("Бот готовий до зчитування!")
    bot.infinity_polling()
