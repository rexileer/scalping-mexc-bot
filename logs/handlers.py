import logging
import asyncio
from asgiref.sync import sync_to_async
from .models import BotLog, LogLevel


class AsyncDatabaseHandler(logging.Handler):
    """
    Обработчик логов, который асинхронно записывает логи в базу данных
    """

    def __init__(self, *args, **kwargs):
        self.loop = None
        super().__init__(*args, **kwargs)

    def emit(self, record):
        try:
            # Форматирование сообщения
            msg = self.format(record)

            # Определение уровня лога
            if record.levelno >= logging.ERROR:
                level = LogLevel.ERROR
            elif record.levelno >= logging.WARNING:
                level = LogLevel.WARNING
            elif record.levelno >= logging.INFO:
                level = LogLevel.INFO
            else:
                level = LogLevel.DEBUG

            # Подготовка дополнительных данных
            extra_data = {
                "logger": record.name,
                "pathname": record.pathname,
                "lineno": record.lineno,
                "funcName": record.funcName,
                "exc_info": record.exc_info is not None,
            }

            # Безопасная проверка наличия running loop
            try:
                loop = asyncio.get_running_loop()
                # Мы внутри async контекста - используем create_task
                asyncio.create_task(self._emit_async(msg, level, extra_data))
            except RuntimeError:
                # Нет running loop - делаем синхронную запись
                BotLog.objects.create(level=level, message=msg, extra_data=extra_data)

        except Exception:
            self.handleError(record)

    async def _emit_async(self, msg, level, extra_data):
        """Асинхронная функция для записи лога в БД"""
        await sync_to_async(BotLog.objects.create)(
            level=level, message=msg, extra_data=extra_data
        )
