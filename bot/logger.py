import logging
import sys
import os

# Добавляем путь к корню проекта для импорта Django модулей
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings")

# Настраиваем базовое логирование (создаём логгер вручную, чтобы контролировать обработчики)
logger = logging.getLogger("TelegramBot")
logger.setLevel(logging.INFO)

if not logger.handlers:
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
    file_handler = logging.FileHandler('bot_logs.log', mode='a')
    file_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
    logger.addHandler(stream_handler)
    logger.addHandler(file_handler)

# Attach Telegram error handler if NOTIFICATION_CHAT_ID is configured
try:
    from django.conf import settings
    from bot.utils.error_notifier import TelegramErrorHandler
    if getattr(settings, 'NOTIFICATION_CHAT_ID', None):
        # Avoid duplicate handlers if module reloaded
        if not any(isinstance(h, TelegramErrorHandler) for h in logger.handlers):
            logger.addHandler(TelegramErrorHandler())
except Exception:
    # Do not fail logging setup
    pass

# Асинхронное логирование в БД
async def log_to_db(message, level='INFO', user=None, extra_data=None):
    """
    Асинхронно записать лог в базу данных.
    
    :param message: Текст сообщения
    :param level: Уровень (INFO, WARNING, ERROR, DEBUG)
    :param user: Объект пользователя (опционально)
    :param extra_data: Дополнительные данные в формате dict (опционально)
    """
    try:
        # Импортируем здесь для избежания циклических импортов
        from logs.services import log_async
        from logs.models import LogLevel
        
        # Маппинг строковых уровней в константы
        level_map = {
            'DEBUG': LogLevel.DEBUG,
            'INFO': LogLevel.INFO,
            'WARNING': LogLevel.WARNING,
            'ERROR': LogLevel.ERROR
        }
        
        # Получаем уровень лога из маппинга или используем INFO по умолчанию
        log_level = level_map.get(level.upper(), LogLevel.INFO)
        
        # Проверяем, что user является объектом модели User или None
        if user is not None:
            # Проверяем, что это объект модели User из приложения users
            from users.models import User
            if not isinstance(user, User):
                logger.warning(f"Передан неверный тип пользователя: {type(user)}")
                user = None
        
        # Убедимся, что extra_data - словарь или None
        if extra_data is not None and not isinstance(extra_data, dict):
            logger.warning(f"extra_data должен быть словарем, получено: {type(extra_data)}")
            try:
                # Пытаемся преобразовать в словарь
                extra_data = {'data': str(extra_data)}
            except:
                extra_data = {'error': 'Невозможно преобразовать данные в словарь'}
        
        # Проверяем, что сообщение - строка
        if not isinstance(message, str):
            message = str(message)
        
        # Асинхронно записываем лог
        await log_async(message, level=log_level, user=user, extra_data=extra_data)
        
    except Exception as e:
        # В случае ошибки логируем в стандартный логгер
        logger.error(f"Ошибка при записи лога в БД: {e}")