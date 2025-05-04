import logging
import os
from datetime import datetime

# Создаем директорию для логов, если она не существует
log_dir = os.path.join(os.getcwd(), 'logs')
os.makedirs(log_dir, exist_ok=True)

# Формируем имя файла лога с датой
log_file = os.path.join(log_dir, f'bot_logs_{datetime.now().strftime("%Y%m%d")}.log')

# Настраиваем логгер
logger = logging.getLogger('bot')
logger.setLevel(logging.INFO)

# Проверяем, есть ли уже обработчики
if not logger.handlers:
    # Создаем форматтер
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    # Добавляем обработчик для файла
    file_handler = logging.FileHandler(log_file, mode='a', encoding='utf-8')
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    # Добавляем обработчик для консоли
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)