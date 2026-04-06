# Використовуємо офіційний образ Python
FROM python:3.10-slim

# Встановлюємо робочу директорію
WORKDIR /app

# КРОК ДЛЯ ВИПРАВЛЕННЯ ПОМИЛКИ 100:
# 1. Замінюємо стандартні дзеркала на стабільні (deb.debian.org)
# 2. Очищуємо кеш apt перед оновленням
RUN sed -i 's/deb.debian.org/ftp.us.debian.org/g' /etc/apt/sources.list && \
    apt-get clean && \
    apt-get update --fix-missing && \
    apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-ukr \
    libgl1-mesa-glx \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Далі все за стандартом
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 10000

CMD ["python", "app.py"]
