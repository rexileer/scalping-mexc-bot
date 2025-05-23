from typing import Dict, Any, Callable, Awaitable
from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery
from bot.utils.bot_logging import log_command, log_user_action, log_callback
from bot.logger import logger
import re

# Паттерн для определения команд: "/" + 1 или более букв/цифр/подчеркиваний
COMMAND_PATTERN = re.compile(r'^/[a-zA-Z0-9_]+')

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
        # Логируем взаимодействие до вызова обработчика
        if isinstance(event, Message):
            # Обработка текстовых сообщений
            user_id = event.from_user.id
            username = event.from_user.username or event.from_user.first_name or 'Unknown'
            
            if event.text:
                # Для команд просто логируем в консоль, детальное логирование будет в обработчиках
                if COMMAND_PATTERN.match(event.text):
                    command = event.text.split()[0]
                    logger.info(f"User {user_id} sent command: {command}")
                else:
                    # Логируем обычное текстовое сообщение
                    text = event.text[:100] + ('...' if len(event.text) > 100 else '')
                    await log_user_action(
                        user_id=user_id,
                        action=f"Отправил сообщение",
                        extra_data={
                            'username': username,
                            'text': text,
                            'chat_id': event.chat.id,
                            'message_type': 'text'
                        }
                    )
            elif event.content_type != 'text':
                # Логируем медиа-контент (фото, видео и т.д.)
                await log_user_action(
                    user_id=user_id,
                    action=f"Отправил {event.content_type}",
                    extra_data={
                        'username': username,
                        'chat_id': event.chat.id,
                        'message_type': event.content_type
                    }
                )
        
        elif isinstance(event, CallbackQuery):
            # Обработка нажатий на кнопки - только логируем в консоль
            # Полное логирование будет происходить в обработчиках callback
            user_id = event.from_user.id
            callback_data = event.data
            
            # Только логируем в консоль, без создания записи в БД
            logger.info(f"User {user_id} pressed button: {callback_data}")
        
        # Вызываем обработчик события
        return await handler(event, data) 