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
def health_check(): return "Scanner Pro Active", 200

def run_web():
    port = int(os.environ.get("PORT", 10000))
    web_app.run(host="0.0.0.0", port=port)

# --- 2. КОНФІГУРАЦІЯ ---
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
AI_KEY = os.environ.get("OPENAI_API_KEY")
bot = telebot.TeleBot(TOKEN)
client = OpenAI(api_key=AI_KEY)

user_data_buffer = {}
buffer_lock = threading.Lock()

# --- 3. ШВИДКЕ ЗЧИТУВАННЯ ТЕКСТУ (OCR) ---
def fast_ocr(file_path):
    try:
        with Image.open(file_path) as img:
            # Оптимізація розміру для слабкого CPU Render
            img.thumbnail((1500, 1500))
            img = img.convert('L
                          
