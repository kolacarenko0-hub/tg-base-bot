import os
import time
import threading
import telebot
from openai import OpenAI
from flask import Flask

# --- 1. ВЕБ-СЕРВЕР (Для стабільності на Render) ---
web_app = Flask(__name__)

@web_app.route('/')
def health_check():
    return "Military Vision AI Active", 200

def run_web():
    port = int(os.environ.get("PORT", 10000))
    web_app.run(host="0.0.0.0", port=port)

# --- 2. КОНФІГУРАЦІЯ ---
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
AI_KEY = os.environ.get("OPENAI_API_KEY")
bot = telebot.TeleBot(TOKEN)
client = OpenAI(api_key=AI_KEY)

# Сховище сесій для обробки альбомів
user_sessions = {}
sessions_lock = threading.Lock()

# --- 3. ЛОГІКА АНАЛІЗУ (GPT-4o-mini Vision) ---
def analyze_images(chat_id):
    with sessions_lock:
        session = user_sessions.get(chat_id)
        if not session:
            return
        image_urls = session['urls']
        user_caption = session['caption'] if session['caption'] else "Об'єкт з наданих матеріалів"

    try:
        # Формуємо запит до нейромережі
        content = [
            {
                "type": "text", 
                "text": f"""Ти — провідний військовий інженер-сапер та аналітик боєприпасів. 
                Проведи глибокий аналіз даних про: {user_caption}.
                
                Твоє завдання — не просто переписати текст, а виявити ВСЮ цінну інформацію.
                
                СТРУКТУРА ЗВІТУ:
                ### 🏷️ НАЗВА ТА ПРИЗНАЧЕННЯ
                (Визнач модель, тип боєприпасу та його основну роль)

                ### 📊 ТЕХНІЧНІ ХАРАКТЕРИСТИКИ (ТТХ)
                (Формат: **Параметр** — Значення. Випиши всі цифри, габарити, вагу ВР, дальності тощо)

                ### 🔍 ОСОБЛИВА ПРИМІТКА ТА ГЛИБОКИЙ АНАЛІЗ
                (Сюди винеси все критично важливе, що не є стандартним ТТХ:
                - Особливості маркування, кольорові смуги, коди.
                - Тип підривника, наявність елементів самоліквідації чи невилучаємості.
                - Будь-які рукописні замітки або схеми на фото.
                - Специфічні нюанси встановлення чи знешкодження, помічені на зображеннях.)

                ### 💡 ВИСНОВОК АНАЛІТИКА
                (Твій професійний підсумок: на що звернути увагу особовому складу при зустрічі з цим об'єктом).

                ПРАВИЛА:
                - ТАБЛИЦІ ЗАБОРОНЕНІ (використовуй список з подвійними зірочками для параметрів).
                - Якщо інформація на фото суперечлива — вкажи про це.
                - Пиши професійно, без зайвої "води"."""
            }
        ]
        
        # Додаємо посилання на всі фото з альбому
        for url in image_urls:
            content.append({
                "type": "image_url",
                "image_url": {"url": url}
            })

        # Виклик моделі GPT-4o-mini (вона швидка і має Vision)
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": content}],
            max_tokens=3000,
            temperature=0.1 # Мінімальна температура для максимальної точності фактів
        )

        final_result = response.choices[0].message.content
        
        # Відправка результату (з розбиттям, якщо текст дуже довгий)
        if len(final_result) > 4096:
            for i in range(0, len(final_result), 4096):
                bot.send_message(chat_id, final_result[i:i+4096], parse_mode="Markdown")
        else:
            bot.send_message(chat_id, final_result, parse_mode="Markdown")

    except Exception as e:
        bot.send_message(chat_id, f"❌ Помилка аналізу: {str(e)}")
    finally:
        with sessions_lock:
            user_sessions.pop(chat_id, None)

# --- 4. ОБРОБНИКИ ПОВІДОМЛЕНЬ ---

@bot.message_handler(content_types=['photo'])
def handle_photos(message):
    chat_id = message.chat.id
    
    # Отримуємо URL фото прямо з серверів Telegram (не завантажуємо на Render)
    try:
        file_info = bot.get_file(message.photo[-1].file_id)
        file_url = f"https://api.telegram.org/file/bot{TOKEN}/{file_info.file_path}"
    except Exception as e:
        print(f"Error getting file: {e}")
        return

    with sessions_lock:
        if chat_id not in user_sessions:
            user_sessions[chat_id] = {'urls': [], 'caption': message.caption, 'timer': None}
            bot.send_chat_action(chat_id, 'typing')
            bot.send_message(chat_id, "📥 Фото прийнято. Аналізую об'єкт...")
        
        user_sessions[chat_id]['urls'].append(file_url)
        
        # Якщо прилетіло нове фото в альбомі — скидаємо таймер
        if user_sessions[chat_id]['timer']:
            user_sessions[chat_id]['timer'].cancel()
        
        # Чекаємо 7 секунд (достатньо, щоб Telegram передав усі фото альбому)
        t = threading.Timer(7.0, analyze_images, args=[chat_id])
        user_sessions[chat_id]['timer'] = t
        t.start()

# --- 5. СТАРТ ТА ОЧИЩЕННЯ (Захист від 409) ---
if __name__ == "__main__":
    # Запуск Flask
    threading.Thread(target=run_web, daemon=True).start()
    
    print("Ініціалізація Vision AI бота...")
    try:
        bot.remove_webhook()
        time.sleep(1)
        # Очищення черги, щоб ігнорувати старі запити
        bot.get_updates(offset=-1, timeout=1)
        print("Черга очищена. Пауза 10 секунд...")
        time.sleep(10)
    except Exception as e:
        print(f"Start warning: {e}")

    print("--- БОТ ГОТОВИЙ ДО РОБОТИ ---")
    
    # Запуск безкінечного опитування
    while True:
        try:
            bot.polling(none_stop=True, interval=2, timeout=60)
        except Exception as e:
            print(f"Polling error: {e}")
            time.sleep(5)
            
