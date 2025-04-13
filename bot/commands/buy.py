import asyncio
from aiogram.types import Message
from asgiref.sync import sync_to_async
from django.utils import timezone
from users.models import Deal
from logger import logger

from mexc_sdk import Trade


async def monitor_order(message: Message, order_id: str):
    try:
        deal = await sync_to_async(Deal.objects.get)(order_id=order_id)
        user = deal.user
        trade_client = Trade(api_key=user.api_key, api_secret=user.api_secret)
        symbol = user.pair.replace("/", "")
    except Exception as e:
        logger.error(f"Ошибка при инициализации мониторинга: {e}")
        await message.answer("Ошибка при запуске мониторинга.")
        return

    while True:
        try:
            order_status = trade_client.query_order(symbol, options={"orderId": order_id})
            status = order_status.get("status")

            if status == "FILLED":
                deal.status = "FILLED"
                deal.updated_at = timezone.now()
                await sync_to_async(deal.save)()
                await message.answer(f"✅ Сделка {deal.side} исполнена!")
                return

            await asyncio.sleep(60)
        except Exception as e:
            logger.error(f"Ошибка в мониторинге ордера {order_id}: {e}")
            await asyncio.sleep(60)
