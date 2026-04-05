import os
import time
import threading
import telebot
from flask import Flask # Додай Flask у requirements.txt

# Твій основний код бота... (extract_text, process_with_progress і т.д.)

# --- МІНІМАЛЬНИЙ ВЕБ-СЕРВЕР ДЛЯ RENDER ---
app = Flask(__name__)

@app.route('/')
def health_check():
    return "Bot is running!", 200

def run_web():
    # Render передає порт через змінну оточення
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

# --- ЗАПУСК ---
if __name__ == "__main__":
    # Запускаємо веб-сервер у фоні
    threading.Thread(target=run_web, daemon=True).start()
    
    print("🚀 Бот запускається на Render...")
    while True:
        try:
            bot.infinity_polling(timeout=60)
        except Exception as e:
            print(f"⚠️ Помилка: {e}")
            time.sleep(15)
