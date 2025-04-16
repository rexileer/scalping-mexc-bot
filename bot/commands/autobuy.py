import asyncio
from aiogram.types import Message
from asgiref.sync import sync_to_async
from django.utils import timezone
from users.models import Deal, User
from logger import logger
from subscriptions.models import Subscription
from bot.utils.user_autobuy_tasks import user_autobuy_tasks
from bot.utils.mexc import handle_mexc_response
from mexc_sdk import Trade




async def autobuy_loop(message: Message, telegram_id: int):
    try:
        user = await sync_to_async(User.objects.get)(telegram_id=telegram_id)
        trade_client = Trade(api_key=user.api_key, api_secret=user.api_secret)
        symbol = user.pair.replace("/", "")
        buy_amount = float(user.buy_amount)
        profit_percent = float(user.profit)
        loss_threshold = float(user.loss)

        active_orders = []
        last_buy_price = None

        while True:
            user = await sync_to_async(User.objects.get)(telegram_id=telegram_id)
            subscription = await sync_to_async(Subscription.objects.filter(user=user).order_by('-expires_at').first)()
            if not subscription or subscription.expires_at < timezone.now():
                user.autobuy = False
                await sync_to_async(user.save)()
                task = user_autobuy_tasks.get(telegram_id)
                if task:
                    task.cancel()
                    del user_autobuy_tasks[telegram_id]
                await message.answer("⛔ Ваша подписка закончилась. Автобай остановлен.")
                break

            ticker_data = trade_client.ticker_price(symbol)
            handle_mexc_response(ticker_data, "Получение цены")
            current_price = float(ticker_data['price'])

            if not last_buy_price or ((last_buy_price - current_price) / last_buy_price * 100) >= loss_threshold:
                buy_order = trade_client.new_order(symbol, "BUY", "MARKET", {"quoteOrderQty": buy_amount})
                handle_mexc_response(buy_order, "Покупка")

                executed_qty = float(buy_order["executedQty"])
                avg_price = float(buy_order["fills"][0]["price"])
                spent = executed_qty * avg_price
                last_buy_price = avg_price
                sell_price = round(avg_price * (1 + profit_percent / 100), 6)

                sell_order = trade_client.new_order(symbol, "SELL", "LIMIT", {
                    "quantity": executed_qty,
                    "price": f"{sell_price:.6f}",
                    "timeInForce": "GTC"
                })
                handle_mexc_response(sell_order, "Продажа")

                await sync_to_async(Deal.objects.create)(
                    user=user,
                    order_id=sell_order['orderId'],
                    symbol=symbol,
                    buy_price=avg_price,
                    quantity=executed_qty,
                    sell_price=sell_price,
                    status="SELL_ORDER_PLACED",
                    is_autobuy=True
                )

                active_orders.append({
                    "order_id": sell_order['orderId'],
                    "buy_price": avg_price,
                    "notified": False
                })

                await message.answer(
                    f"🟢 *КУПЛЕНО*\n\n"
                    f"📉 Цена: `{avg_price:.6f}` USDT\n"
                    f"📦 Кол-во: `{executed_qty:.4f}` {symbol[:-4]}\n"
                    f"💸 Потрачено: `{spent:.2f}` USDT\n\n"
                    f"📈 Продажа по: `{sell_price:.6f}` USDT",
                    parse_mode="Markdown"
                )

            still_active = []
            for order_info in active_orders:
                result = await monitor_order_autobuy(message, trade_client, symbol, order_info, telegram_id, loss_threshold)
                if result == "ACTIVE":
                    still_active.append(order_info)
            active_orders = still_active

            await asyncio.sleep(user.pause if not active_orders else 60)

    except asyncio.CancelledError:
        raise
    except Exception as e:
        logger.error(f"Ошибка в autobuy_loop для {telegram_id}: {e}")
        await message.answer(f"❌ Произошла ошибка: {e}")
        await asyncio.sleep(30)



async def monitor_order_autobuy(message: Message, trade_client: Trade, symbol: str, order_info: dict, telegram_id: int, loss_threshold: float):
    try:
        order_id = order_info["order_id"]
        buy_price = order_info["buy_price"]
        if order_info.get("notified") is None:
            order_info["notified"] = False

        order_status = trade_client.query_order(symbol, options={"orderId": order_id})
        handle_mexc_response(order_status, "Проверка ордера")
        status = order_status.get("status")

        if status == "FILLED":
            deal = await sync_to_async(Deal.objects.get)(order_id=order_id)
            deal.status = "FILLED"
            deal.updated_at = timezone.now()
            await sync_to_async(deal.save)()

            total_received = float(order_status.get("cummulativeQuoteQty", 0))
            quantity = float(order_status.get("executedQty", 0))
            sell_price = total_received / quantity if quantity else 0
            profit = total_received - (deal.buy_price * quantity)

            await message.answer(
                f"🔁 *СДЕЛКА ЗАВЕРШЕНА*\n\n"
                f"📦 Кол-во: `{quantity:.4f}` {symbol[:-4]}\n"
                f"💰 Продано по: `{sell_price:.6f}` USDT\n"
                f"📊 Прибыль: `{profit:.2f}` USDT",
                parse_mode="Markdown"
            )
            return "FILLED"

        price_data = trade_client.ticker_price(symbol)
        handle_mexc_response(price_data, "Проверка цены")
        current_price = float(price_data['price'])
        drop_percent = ((buy_price - current_price) / buy_price) * 100

        if drop_percent >= loss_threshold and not order_info["notified"]:
            await message.answer(
                f"⚠️ *Падение цены*\n\n"
                f"💱 Текущая: `{current_price:.6f}` {symbol[-4:]}\n"
                f"🔻 Снижение: `{drop_percent:.2f}%`\n"
                f"📌 Ордер: `{order_id}`",
                parse_mode="Markdown"
            )
            order_info["notified"] = True

        return "ACTIVE"

    except asyncio.CancelledError:
        return "CANCELLED"
    except Exception as e:
        logger.error(f"Ошибка мониторинга ордера {order_id}: {e}")
        await message.answer(f"⚠️ Ошибка проверки ордера {order_id}: {e}")
        return "ACTIVE"
