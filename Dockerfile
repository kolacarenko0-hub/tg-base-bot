# Використовуємо офіційний образ Python
FROM python:3.10-slim

# Встановлюємо робочу директорію
WORKDIR /app

# Налаштування системних пакетів з виправленням помилки 100
RUN apt-get update --fix-missing && \
    apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-ukr \
    libgl1-mesa-glx \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Копіюємо файл залежностей
COPY requirements.txt .

# Встановлюємо бібліотеки Python
RUN pip install --no-cache-dir -r requirements.txt

# Копіюємо решту коду
COPY . .

# Експортуємо порт
EXPOSE 10000

# Запуск бота
CMD ["python", "app.py"]
