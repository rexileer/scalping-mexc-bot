from aiogram.types import Message, Update
from aiogram import BaseMiddleware
from typing import Callable, Dict, Any, Awaitable
from bot.logger import logger
from users.models import User 
from subscriptions.models import Subscription
from datetime import datetime, timezone

# Настройки оплаты (можно потом в settings вытащить)
PAYMENT_WALLET = "TY43ubA82J5mrViFwAsNpNLkNLaj2rvx1Z"
PAYMENT_NETWORK = "TRC20"

PAYMENT_MESSAGE = (
    f"🔒 Для получения доступа к боту:\n\n"
    f"1️⃣ Оплатите 100 USDT в сети {PAYMENT_NETWORK} на кошелёк:\n"
    f"<code>{PAYMENT_WALLET}</code>\n\n"
    f"2️⃣ После оплаты отправьте скриншот и TXID в ЛС 👉 @ScalpingBotSupport\n\n"
    f"Перед оплатой рекомендуем нажать /start для актуализации информации."
)

class AccessMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[Update, Dict[str, Any]], Awaitable[Any]],
        event: Update,
        data: Dict[str, Any]
    ) -> Any:
        message = event.message

        if message:
            telegram_user = message.from_user

            try:
                # Добавление юзера, если нет
                user, _ = await User.objects.aget_or_create(
                    telegram_id=telegram_user.id,
                    defaults={"name": telegram_user.username or ""}
                )
            except Exception as e:
                logger.error(f"DB error while checking/creating user: {e}")
                return  # Лучше блокировать, чем продолжать с ошибкой

            # Проверка подписки
            now = datetime.now(timezone.utc)
            try:
                subscription = await Subscription.objects.filter(
                    telegram_id=telegram_user.id,
                    expires_at__gte=now
                ).afirst()
            except Exception as e:
                logger.error(f"DB error while checking subscription: {e}")
                subscription = None

            # Нет подписки — выводим сообщение
            if not subscription:
                await message.answer(PAYMENT_MESSAGE, parse_mode="HTML")
                return

        return await handler(event, data)
