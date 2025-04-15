import asyncio
from aiogram.types import Message
from asgiref.sync import sync_to_async
from django.utils import timezone
from users.models import Deal, User
from logger import logger
from subscriptions.models import Subscription
from bot.utils.user_autobuy_tasks import user_autobuy_tasks

from mexc_sdk import Trade

async def autobuy_loop(message: Message, telegram_id: int):
    try:
        user = await sync_to_async(User.objects.get)(telegram_id=telegram_id)
        trade_client = Trade(api_key=user.api_key, api_secret=user.api_secret)
        # Работаем с парой так, как сохранена в базе (например, "KAS/USDT")
        symbol = user.pair.replace("/", "")
        buy_amount = float(user.buy_amount)
        profit_percent = float(user.profit)
        loss_threshold = float(user.loss)

        active_orders = []  # хранит данные об открытых ордерах
        last_buy_price = None

        while True:
            user = await sync_to_async(User.objects.get)(telegram_id=telegram_id)
            subscription = await sync_to_async(Subscription.objects.filter(user=user).order_by('-end_date').first)()

            if not subscription or subscription.expires_at < timezone.now():
                user.autobuy = False
                await sync_to_async(user.save)()

                # Удалим задачу из глобального хранилища
                task = user_autobuy_tasks.get(telegram_id)
                if task:
                    task.cancel()
                    del user_autobuy_tasks[telegram_id]

                await message.answer("⛔ Ваша подписка закончилась. Автобай остановлен.")
                logger.info(f"Autobuy stopped for {telegram_id} due to expired subscription")
                break  # Выходим из цикла
            
            current_price = float(trade_client.ticker_price(symbol)['price'])

            # Если это первая покупка или цена упала на заданный процент от последней покупки
            if not last_buy_price or ((last_buy_price - current_price) / last_buy_price * 100) >= loss_threshold:
                # Совершаем покупку по рынку на сумму buy_amount
                buy_order = trade_client.new_order(symbol, "BUY", "MARKET", {"quoteOrderQty": buy_amount})
                executed_qty = float(buy_order["executedQty"])
                avg_price = float(buy_order["fills"][0]["price"])
                spent = executed_qty * avg_price

                # Обновляем последнюю цену покупки
                last_buy_price = avg_price

                # Целевая цена продажи с заданной прибылью
                sell_price = round(avg_price * (1 + profit_percent / 100), 6)

                # Размещаем лимитный ордер на продажу
                sell_order = trade_client.new_order(symbol, "SELL", "LIMIT", {
                    "quantity": executed_qty,
                    "price": f"{sell_price:.6f}",
                    "timeInForce": "GTC"
                })

                # Сохраняем сделку с флагом, что она автопокупка
                deal = await sync_to_async(Deal.objects.create)(
                    user=user,
                    order_id=sell_order['orderId'],
                    symbol=symbol,
                    buy_price=avg_price,
                    quantity=executed_qty,
                    sell_price=sell_price,
                    status="SELL_ORDER_PLACED",
                    is_autobuy=True
                )

                # Добавляем данные ордера в список активных ордеров
                active_orders.append({
                    "order_id": sell_order['orderId'],
                    "buy_price": avg_price,
                    "notified": False  # флаг, чтобы уведомление о падении цены отправлялось лишь один раз
                })

                await message.answer(
                    f"✅ КУПЛЕНО\n\n{executed_qty:.2f} {symbol[:-4]} по {avg_price:.6f} USDT\n"
                    f"Потрачено: {spent:.6f} USDT\n\n📈 Продажа по {sell_price:.6f} USDT"
                )
                logger.info(f"BUY + SELL for {user.telegram_id}: {executed_qty} {symbol} @ {avg_price} -> {sell_price}")

            # Мониторим каждый активный ордер
            still_active = []
            for order_info in active_orders:
                result = await monitor_order_autobuy(message, trade_client, symbol, order_info, telegram_id, loss_threshold)
                if result == "ACTIVE":
                    still_active.append(order_info)
            active_orders = still_active

            # Если все ордера завершены, выполняем паузу перед новой покупкой
            if not active_orders:
                await asyncio.sleep(user.pause)
            else:
                # Если есть активные ордера, ждем немного меньше, чтобы проверить их чаще
                await asyncio.sleep(60)

    except asyncio.CancelledError:
        logger.info(f"Autobuy cancelled for {telegram_id}")
        raise
    except Exception as e:
        logger.error(f"Ошибка в autobuy_loop для {telegram_id}: {e}")
        await asyncio.sleep(30)


async def monitor_order_autobuy(message: Message, trade_client: Trade, symbol: str, order_info: dict, telegram_id: int, loss_threshold: float):
    try:
        order_id = order_info["order_id"]
        buy_price = order_info["buy_price"]
        # Используем флаг, сохранённый в order_info, чтобы не повторять уведомление
        if order_info.get("notified") is None:
            order_info["notified"] = False

        order_status = trade_client.query_order(symbol, options={"orderId": order_id})
        status = order_status.get("status")

        if status == "FILLED":
            deal = await sync_to_async(Deal.objects.get)(order_id=order_id)
            deal.status = "FILLED"
            deal.updated_at = timezone.now()
            await sync_to_async(deal.save)()
            await message.answer(f"✅ Сделка исполнена! Ордер {order_id} закрыт.")
            return "FILLED"

        current_price = float(trade_client.ticker_price(symbol)['price'])
        drop_percent = ((buy_price - current_price) / buy_price) * 100

        if drop_percent >= loss_threshold and not order_info["notified"]:
            await message.answer(
                f"⚠️ Цена упала на {drop_percent:.2f}% от покупки ({current_price:.6f} {symbol[-4:]}) по ордеру {order_id}."
            )
            order_info["notified"] = True

        return "ACTIVE"

    except asyncio.CancelledError:
        logger.info(f"Monitor cancelled for order {order_id}, user {telegram_id}")
        return "CANCELLED"
    except Exception as e:
        logger.error(f"Ошибка мониторинга в autobuy для ордера {order_id}: {e}")
        return "ACTIVE"
