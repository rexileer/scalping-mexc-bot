FROM python:3.11-slim

WORKDIR /app

# Установка системных зависимостей и Node.js
RUN apt-get update && apt-get install -y \
    gcc \
    postgresql-client \
    curl \
    gnupg \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

# Копируем файлы зависимостей
COPY requirements.txt .

# Копируем локальный пакет mexc-sdk
COPY mexc-sdk-1.0.0 /app/mexc-sdk-1.0.0

# Устанавливаем зависимости
RUN pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir -e /app/mexc-sdk-1.0.0 && \
    pip install --no-cache-dir pytest-asyncio pytest-django

# Создаем непривилегированного пользователя
RUN useradd -m appuser

# Создаем необходимые директории и настраиваем права
RUN mkdir -p /app/logs && \
    chown -R appuser:appuser /app

# Копируем код приложения
COPY --chown=appuser:appuser . .

# Устанавливаем переменные окружения
ENV PYTHONPATH=/app
ENV DJANGO_SETTINGS_MODULE=core.settings
ENV TESTING=1

# Переключаемся на непривилегированного пользователя
USER appuser

# Запускаем тесты
CMD ["pytest", "tests/", "-v"] 