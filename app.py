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

# --- 1. ВЕБ-СЕРВЕР ДЛЯ RENDER ---
web_app = Flask(__name__)
@web_app.route('/')
def health_check(): return "Multi-Scanner Processor Active", 200

def run_web():
    port = int(os.environ.get("PORT", 10000))
    web_app.run(host="0.0.0.0", port=port)

# --- 2. КОНФІГУРАЦІЯ ---
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
AI_KEY = os.environ.get("OPENAI_API_KEY")
bot = telebot.TeleBot(TOKEN)
client = OpenAI(api_key=AI_KEY)

# Глобальний буфер для збереження тексту з різних фото одного користувача
user_data_buffer = {}
buffer_lock = threading.Lock()

# --- 3. ШВИДКЕ ЗЧИТУВАННЯ ТЕКСТУ (OCR
