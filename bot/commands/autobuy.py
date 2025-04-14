import asyncio
from aiogram.types import Message
from asgiref.sync import sync_to_async
from django.utils import timezone
from users.models import Deal, User
from logger import logger

from mexc_sdk import Trade


async def autobuy_loop(message: Message, telegram_id: int):
    try:
        while True:
            user = await sync_to_async(User.objects.get)(telegram_id=telegram_id)

            if not user.pair or not user.buy_amount or not user.profit:
                await message.answer("❗ Укажите торговую пару, сумму и процент прибыли (/pair /amount /profit)")
                return

            symbol = user.pair.replace("/", "")
            trade_client = Trade(api_key=user.api_key, api_secret=user.api_secret)
            buy_amount = float(user.buy_amount)
            profit_percent = float(user.profit)

            # Покупка
            buy_order = trade_client.new_order(symbol, "BUY", "MARKET", {"quoteOrderQty": buy_amount})
            executed_qty = float(buy_order["executedQty"])
            avg_price = float(buy_order["fills"][0]["price"])
            spent = executed_qty * avg_price

            # Выставляем лимитный ордер на продажу
            sell_price = round(avg_price * (1 + profit_percent / 100), 6)
            sell_order = trade_client.new_order(symbol, "SELL", "LIMIT", {
                "quantity": executed_qty,
                "price": f"{sell_price:.6f}",
                "timeInForce": "GTC"
            })

            # Сохраняем сделку
            order_id = sell_order['orderId']
            deal = await sync_to_async(Deal.objects.create)(
                user=user,
                order_id=order_id,
                symbol=symbol,
                buy_price=avg_price,
                quantity=executed_qty,
                sell_price=sell_price,
                status="SELL_ORDER_PLACED",
                is_autobuy=True
            )

            await message.answer(
                f"✅ КУПЛЕНО\n\n{executed_qty:.2f} {symbol[:-4]} по {avg_price:.6f} USDT\n"
                f"Потрачено: {spent:.6f} USDT\n\n📈 Продажа по {sell_price:.6f} USDT")

            # Мониторинг сделки с уведомлением
            await monitor_order_autobuy(message, order_id, avg_price, telegram_id)

            await asyncio.sleep(user.pause)

    except asyncio.CancelledError:
        logger.info(f"Autobuy cancelled for {telegram_id}")
        await message.answer("⛔ Автобай был остановлен.")
        raise  # пробрасываем дальше, чтобы задача считалась реально отменённой
    except Exception as e:
        logger.error(f"Ошибка в autobuy_loop для {telegram_id}: {e}")
        await asyncio.sleep(30)


async def monitor_order_autobuy(message: Message, order_id: str, buy_price: float, telegram_id: int):
    try:
        user = await sync_to_async(User.objects.get)(telegram_id=telegram_id)
        trade_client = Trade(api_key=user.api_key, api_secret=user.api_secret)
        symbol = user.pair.replace("/", "")
        notified = False

        while True:
            order_status = trade_client.query_order(symbol, options={"orderId": order_id})
            status = order_status.get("status")

            if status == "FILLED":
                deal = await sync_to_async(Deal.objects.get)(order_id=order_id)
                deal.status = "FILLED"
                deal.updated_at = timezone.now()
                await sync_to_async(deal.save)()
                await message.answer("✅ Сделка исполнена!")
                return

            current_price = float(trade_client.ticker_price(symbol)['price'])
            drop_percent = ((buy_price - current_price) / buy_price) * 100

            if drop_percent >= user.loss and not notified:
                await message.answer(
                    f"⚠️ Цена упала на {drop_percent:.2f}% от покупки ({current_price:.6f} USDT)")
                notified = True

            await asyncio.sleep(60)

    except asyncio.CancelledError:
        logger.info(f"Monitor cancelled for order {order_id}, user {telegram_id}")
        return
    except Exception as e:
        logger.error(f"Ошибка мониторинга в autobuy: {e}")
        await asyncio.sleep(60)
