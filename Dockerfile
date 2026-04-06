# Використовуємо образ Python (slim версія легша і швидша)
FROM python:3.10-slim

# ВАЖЛИВИЙ КРОК: Встановлюємо системні пакети для OCR
# tesseract-ocr - сам двигун
# tesseract-ocr-ukr - українська мова
# libgl1-mesa-glx - бібліотека для коректної роботи з картинками (Pillow/OpenCV)
RUN apt-get update && apt-get install -y \
    tesseract-ocr \
    tesseract-ocr-ukr \
    libgl1-mesa-glx \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Встановлюємо робочу папку
WORKDIR /app

# Копіюємо файл залежностей
COPY requirements.txt .

# Встановлюємо бібліотеки Python
RUN pip install --no-cache-dir -r requirements.txt

# Копіюємо весь інший код (app.py тощо)
COPY . .

# Render автоматично надає порт через змінну оточення PORT
EXPOSE 10000

# Запуск бота
CMD ["python", "app.py"]
