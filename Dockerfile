# Використовуємо стабільний образ Ubuntu з вбудованим Python
FROM ubuntu:22.04

# Встановлюємо неінтерактивний режим (щоб не питало про часові пояси)
ENV DEBIAN_FRONTEND=noninteractive

# Робоча директорія
WORKDIR /app

# Встановлюємо Python та системні пакети для OCR
RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    tesseract-ocr \
    tesseract-ocr-ukr \
    libgl1-mesa-glx \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Створюємо посилання, щоб команда python працювала як python3
RUN ln -s /usr/bin/python3 /usr/bin/python

# Копіюємо залежності
COPY requirements.txt .

# Встановлюємо бібліотеки Python
RUN pip install --no-cache-dir -r requirements.txt

# Копіюємо решту коду
COPY . .

# Експортуємо порт для Render
EXPOSE 10000

# Запуск бота
CMD ["python", "app.py"]
