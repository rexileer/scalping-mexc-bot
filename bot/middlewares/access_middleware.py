from aiogram.types import Message, Update
from aiogram import BaseMiddleware
from typing import Callable, Dict, Any, Awaitable
from bot.logger import logger
from users.models import User 
from subscriptions.models import Subscription
from editing.models import BotMessageForSubscription
from datetime import datetime, timezone
from django.db.utils import OperationalError
from bot.constants import DEFAULT_PAYMENT_MESSAGE, PAIR
from aiogram.types import FSInputFile


class AccessMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[Update, Dict[str, Any]], Awaitable[Any]],
        event: Update,
        data: Dict[str, Any]
    ) -> Any:
        # Проверяем, что событие — это сообщение
        if isinstance(event, Message):
            message = event

            telegram_user = message.from_user

            try:
                # Добавление юзера, если нет (по telegram_id; pair задаем через defaults)
                user, _ = await User.objects.aget_or_create(
                    telegram_id=telegram_user.id,
                    defaults={
                        "name": telegram_user.username or "",
                        "pair": PAIR,
                    },
                )
            except Exception as e:
                logger.error(f"DB error while checking/creating user: {e}")
                return  # Лучше блокировать, чем продолжать с ошибкой

            # Проверка подписки
            now = datetime.now(timezone.utc)
            try:
                subscription = await Subscription.objects.filter(
                    user=user,
                    expires_at__gte=now
                ).afirst()
            except Exception as e:
                logger.error(f"DB error while checking subscription: {e}")
                subscription = None

            # Нет подписки — выводим сообщение
            if not subscription:
                # Пробуем получить кастомное сообщение из базы
                try:
                    custom_message = await BotMessageForSubscription.objects.afirst()
                    text_to_send = custom_message.text if custom_message else DEFAULT_PAYMENT_MESSAGE
                except OperationalError:
                    # База ещё не готова, или миграции не применены
                    text_to_send = DEFAULT_PAYMENT_MESSAGE
                except Exception as e:
                    logger.error(f"Error while fetching subscription message: {e}")
                    text_to_send = DEFAULT_PAYMENT_MESSAGE
                if custom_message and custom_message.image:
                    file = FSInputFile(custom_message.image.path)
                    await message.answer_photo(file, text_to_send, parse_mode="HTML")
                    return
                await message.answer(text_to_send, parse_mode="HTML")
                return

        return await handler(event, data)