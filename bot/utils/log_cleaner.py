import asyncio
import logging
from datetime import datetime
from asgiref.sync import sync_to_async
from logs.models import BotLog
from django.utils import timezone
from datetime import timedelta

logger = logging.getLogger('TelegramBot')

async def cleanup_logs_task(interval_minutes=30, retention_days=7):
    """
    Асинхронная задача для периодической очистки старых логов
    
    :param interval_minutes: Интервал между очистками в минутах
    :param retention_days: Количество дней хранения логов
    """
    while True:
        try:
            # Получаем дату, старше которой нужно удалить логи
            cutoff_date = timezone.now() - timedelta(days=retention_days)
            
            # Удаляем логи старше cutoff_date
            deleted_count, _ = await sync_to_async(BotLog.objects.filter(
                timestamp__lt=cutoff_date
            ).delete)()
            
            # Логируем результат
            current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            if deleted_count > 0:
                logger.info(f"[{current_time}] Очистка логов: удалено {deleted_count} записей старше {retention_days} дней")
            else:
                logger.debug(f"[{current_time}] Очистка логов: нет записей для удаления")
                
        except Exception as e:
            logger.error(f"Ошибка при очистке логов: {e}")
        
        # Ждем указанное время до следующей очистки
        await asyncio.sleep(interval_minutes * 60)  # переводим минуты в секунды

async def start_log_cleaner(retention_days=7):
    """
    Запускает задачу очистки логов
    
    :param retention_days: Количество дней хранения логов
    :return: Запущенная задача
    """
    logger.info(f"Запуск планировщика очистки логов (интервал: 30 минут, хранение: {retention_days} дней)")
    return asyncio.create_task(cleanup_logs_task(interval_minutes=30, retention_days=retention_days)) 