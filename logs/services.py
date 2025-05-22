import asyncio
import json
from asgiref.sync import sync_to_async
from django.utils import timezone
from datetime import timedelta
from .models import BotLog, LogLevel

async def log_async(
    message, 
    level=LogLevel.INFO, 
    user=None, 
    extra_data=None
):
    """
    Асинхронно записывает лог в базу данных
    
    :param message: Текст сообщения
    :param level: Уровень логирования (DEBUG, INFO, WARNING, ERROR)
    :param user: Объект пользователя (опционально)
    :param extra_data: Дополнительные данные в формате dict (опционально)
    """
    await sync_to_async(BotLog.objects.create)(
        level=level,
        user=user,
        message=message,
        extra_data=extra_data
    )

async def cleanup_old_logs_async(days=7):
    """
    Асинхронно удаляет логи старше указанного количества дней
    
    :param days: Количество дней, после которых логи удаляются
    """
    cutoff_date = timezone.now() - timedelta(days=days)
    deleted_count, _ = await sync_to_async(BotLog.objects.filter(
        timestamp__lt=cutoff_date
    ).delete)()
    
    return deleted_count 