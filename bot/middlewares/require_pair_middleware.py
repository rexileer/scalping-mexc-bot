from aiogram import BaseMiddleware
from aiogram.types import Message
from typing import Callable, Awaitable, Dict, Any
from users.models import User

class RequirePairMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[Message, Dict[str, Any]], Awaitable[Any]],
        event: Message,
        data: Dict[str, Any]
    ) -> Any:
        telegram_id = event.from_user.id

        try:
            user = User.objects.get(telegram_id=telegram_id)
            if not user.pair:
                await event.answer("❗️Вы не выбрали торговую пару. Введите /pair для выбора.")
                return
        except User.DoesNotExist:
            await event.answer("❗️Пользователь не найден.")
            return

        return await handler(event, data)
