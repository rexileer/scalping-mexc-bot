import asyncio
from aiogram.types import Message
from asgiref.sync import sync_to_async
from django.utils import timezone
from users.models import Deal
from logger import logger
from bot.utils.mexc import handle_mexc_response
from mexc_sdk import Trade


async def monitor_order(message: Message, order_id: str):
    try:
        logger.info(f"Запуск мониторинга ордера {order_id} для пользователя {message.from_user.id}")
        # Получаем клиента и пару для пользователя
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
            handle_mexc_response(order_status, "Проверка ордера")
            status = order_status.get("status")
            logger.info(f"Статус ордера {order_id}: {status}")
            if status == "CANCELED":
                deal.status = "CANCELED"
                deal.updated_at = timezone.now()
                await sync_to_async(deal.save)()
                await message.answer(
                    f"❌ СДЕЛКА {order_id} ОТМЕНЕНА\n\n "
                    f"🔁 Покупка: {deal.quantity:.2f} {deal.symbol[:3]} по {deal.buy_price:.6f} {deal.symbol[3:]}\n"
                    f"📈 Продажа: {deal.quantity:.2f} {deal.symbol[:3]} по {deal.sell_price:.6f} {deal.symbol[3:]}\n\n"    
                )
                return

            if status == "FILLED":
                deal.status = "FILLED"
                deal.updated_at = timezone.now()
                await sync_to_async(deal.save)()

                buy_total = deal.quantity * deal.buy_price
                sell_total = deal.quantity * deal.sell_price
                profit = sell_total - buy_total
                symbol = deal.symbol
                base = symbol[:3]
                quote = symbol[3:]

                text = (
                    f"✅ СДЕЛКА ИСПОЛНЕНА\n\n"
                    f"🔁 Покупка: {deal.quantity:.2f} {base} по {deal.buy_price:.6f} {quote}\n"
                    f"📈 Продажа: {deal.quantity:.2f} {base} по {deal.sell_price:.6f} {quote}\n\n"
                    f"💰 Прибыль: {profit:+.6f} {quote}"
                )

                await message.answer(text)
                return


            await asyncio.sleep(10)
        except Exception as e:
            logger.error(f"Ошибка в мониторинге ордера {order_id}: {e}")
            await asyncio.sleep(60)