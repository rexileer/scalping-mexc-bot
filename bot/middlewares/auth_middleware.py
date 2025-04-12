from aiogram import BaseMiddleware
from aiogram.types import Message
from typing import Callable, Dict, Any, Awaitable
from mexc_sdk import Spot
from users.models import User
from commands.states import APIAuth
from django.core.exceptions import ObjectDoesNotExist
from aiogram.fsm.context import FSMContext
from bot.logger import logger

ALLOWED_COMMANDS = ["/help", "/set_keys"]


class AuthMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[Message, Dict[str, Any]], Awaitable[Any]],
        event: Message,
        data: Dict[str, Any]
    ) -> Any:
        message: Message = event
        state: FSMContext = data.get("state")
        current_state = await state.get_state()
        telegram_id = message.from_user.id

        logger.info(f"Received message from {telegram_id}: {message.text}")
        logger.info(f"Current state: {current_state}")

        # Не текст? — уведомим
        if not message.text:
            await message.answer("Пожалуйста, используйте текстовые команды.")
            return

        # Разрешённые команды
        if any(message.text.startswith(cmd) for cmd in ALLOWED_COMMANDS):
            logger.info(f"Allowed command received: {message.text}")
            return await handler(event, data)

        # В процессе ввода ключей — пускаем
        if current_state in (APIAuth.waiting_for_api_key.state, APIAuth.waiting_for_api_secret.state):
            logger.info("User is in API key setup state, allowing command.")
            return await handler(event, data)

        # Проверка авторизации
        try:
            user = await User.objects.aget(telegram_id=telegram_id)
        except ObjectDoesNotExist:
            logger.warning(f"User {telegram_id} not found.")
            await message.answer("Вы не зарегистрированы. Используйте /set_keys для авторизации.")
            return

        try:
            if not user.api_key or not user.api_secret:
                logger.warning(f"User {telegram_id} has no API keys.")
                await message.answer("Пожалуйста, сначала введите API ключи через /set_keys.")
                return

            spot = Spot(api_key=user.api_key, api_secret=user.api_secret)
            spot.account()
        except Exception as e:
            logger.error(f"Ошибка при проверке API ключей: {e}")
            await message.answer("Неверные API ключи. Пожалуйста, повторите ввод через /set_keys.")
            return

        # Всё хорошо — пускаем
        return await handler(event, data)
