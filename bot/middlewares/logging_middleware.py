from typing import Dict, Any, Callable, Awaitable
from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery
from bot.utils.bot_logging import log_user_action

class LoggingMiddleware(BaseMiddleware):
    """
    Middleware для логирования всех сообщений и callback-запросов от пользователей бота
    """
    async def __call__(
        self,
        handler: Callable[[Message, Dict[str, Any]], Awaitable[Any]],
        event: Message | CallbackQuery,
        data: Dict[str, Any]
    ) -> Any:
        # Вызываем обработчик события
        result = await handler(event, data)
        
        # Логируем только если обработчик не выполнил собственное логирование
        # Мы не будем логировать здесь, основные команды будут логироваться
        # в их собственных обработчиках
        
        # Для фоновых или необработанных событий можно добавить логирование здесь
        
        return result 