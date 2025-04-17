import asyncio
from aiogram.types import Message
from asgiref.sync import sync_to_async
from django.utils import timezone
from users.models import Deal, User
from subscriptions.models import Subscription
from bot.utils.user_autobuy_tasks import user_autobuy_tasks
from bot.utils.mexc import handle_mexc_response
from mexc_sdk import Trade
from logger import logger
from decimal import Decimal

MAX_FAILS = 5 # Максимальное количество неудачных попыток до остановки автобая

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
        fail_count = 0

        while True:
            try:
                # Проверка подписки
                user = await sync_to_async(User.objects.get)(telegram_id=telegram_id)
                subscription = await sync_to_async(
                    Subscription.objects.filter(user=user).order_by('-expires_at').first
                )()
                if not subscription or subscription.expires_at < timezone.now():
                    user.autobuy = False
                    await sync_to_async(user.save)()
                    task = user_autobuy_tasks.get(telegram_id)
                    if task:
                        task.cancel()
                        del user_autobuy_tasks[telegram_id]
                    await message.answer("⛔ Ваша подписка закончилась. Автобай остановлен.")
                    break

                # Получение текущей цены
                ticker_data = trade_client.ticker_price(symbol)
                handle_mexc_response(ticker_data, "Получение цены")
                current_price = float(ticker_data["price"])

                # Проверка условий для покупки
                price_dropped = last_buy_price and ((last_buy_price - current_price) / last_buy_price * 100) >= loss_threshold
                if not last_buy_price or price_dropped:
                    buy_order = trade_client.new_order(symbol, "BUY", "MARKET", {"quoteOrderQty": buy_amount})
                    handle_mexc_response(buy_order, "Покупка")
                    order_id = buy_order["orderId"]

                    # 2. Подтягиваем детали через query_order
                    order_info = trade_client.query_order(symbol, {"orderId": order_id})
                    logger.info(f"Детали ордера {order_id}: {order_info}")

                    executed_qty = float(order_info.get("executedQty", 0))
                    if executed_qty == 0:
                        await message.answer("❗ Ошибка при создании ордера (executedQty=0).")
                        return

                    spent = float(order_info["cummulativeQuoteQty"])  # 0.999371
                    if spent == 0:
                        await message.answer("❗ Ошибка при создании ордера (spent=0).")
                        return
                    
                    real_price = spent / executed_qty if executed_qty > 0 else 0
                    
                    # 4. Считаем цену продажи
                    profit_percent = float(user.profit)
                    sell_price = round(real_price * (1 + profit_percent / 100), 6)
                    last_buy_price = real_price

                    # Создание лимитного ордера на продажу
                    sell_order = trade_client.new_order(symbol, "SELL", "LIMIT", {
                        "quantity": executed_qty,
                        "price": f"{sell_price:.6f}",
                        "timeInForce": "GTC"
                    })
                    handle_mexc_response(sell_order, "Продажа")
                    sell_order_id = sell_order["orderId"]
                    logger.info(f"SELL ордер {sell_order_id} выставлен на {sell_price:.6f} {symbol[3:]}")
                    sell_order_info = trade_client.query_order(symbol, {"orderId": sell_order_id})
                    # Сохраняем ордер в базу
                    # Получаем следующий номер
                    last_number = await sync_to_async(
                        lambda: Deal.objects.filter(user=user).count()
                    )()
                    user_order_number = last_number + 1
                    
                    await sync_to_async(Deal.objects.create)(
                        user=user,
                        order_id=sell_order_id,
                        user_order_number=user_order_number,
                        symbol=symbol,
                        buy_price=real_price,
                        quantity=executed_qty,
                        sell_price=sell_price,
                        status="SELL_ORDER_PLACED",
                        is_autobuy=True
                    )

                    active_orders.append({
                        "order_id": sell_order_id,
                        "buy_price": real_price,
                        "notified": False,
                        "user_order_number": user_order_number,
                    })

                    await message.answer(
                        f"🟢 *СДЕЛКА {user_order_number} ОТКРЫТА*\n\n"
                        f"📉 Куплено по: `{real_price:.6f}` {symbol[3:]}\n"
                        f"📦 Кол-во: `{executed_qty:.4f}` {symbol[:3]}\n"
                        f"💸 Потрачено: `{spent:.2f}` {symbol[3:]}\n\n"
                        f"📈 Лимит на продажу: `{sell_price:.6f}` {symbol[3:]}",
                        parse_mode="Markdown"
                    )

                # Проверка активных ордеров
                still_active = []
                for sell_order_info in active_orders:
                    result = await monitor_order_autobuy(
                        message=message,
                        trade_client=trade_client,
                        symbol=symbol,
                        order_info=sell_order_info,
                        telegram_id=telegram_id,
                        loss_threshold=loss_threshold,
                    )
                    if result == "ACTIVE":
                        still_active.append(sell_order_info)
                active_orders = still_active

                # Настройка интервалов
                short_check_interval = 7  # сек — частота проверки активных ордеров

                if not active_orders:
                    last_buy_price = None
                    logger.info(f"Пауза автобая для юзера {telegram_id}: {user.pause} секунд ")
                    await asyncio.sleep(user.pause)
                # Последняя строка перед концом цикла:
                await asyncio.sleep(short_check_interval if active_orders else user.pause)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"Ошибка в autobuy_loop для {telegram_id}: {e}")
                await message.answer(f"❌ Произошла ошибка в AutoBuy: {e}")
                fail_count += 1
                if fail_count >= MAX_FAILS:
                    await message.answer("⛔ Максимальное количество ошибок достигнуто. Автобай остановлен.")
                    user.autobuy = False
                    await sync_to_async(user.save)()
                    task = user_autobuy_tasks.get(telegram_id)
                    if task:
                        task.cancel()
                        del user_autobuy_tasks[telegram_id]
                    break
                await asyncio.sleep(30)
                continue

    except asyncio.CancelledError:
        raise
    except Exception as e:
        logger.error(f"Ошибка в autobuy_loop при запуске для {telegram_id}: {e}")
        await message.answer(f"❌ Произошла ошибка при запуске AutoBuy: {e}")



async def monitor_order_autobuy(
    message: Message,
    trade_client: Trade,
    symbol: str,
    order_info: dict,
    telegram_id: int,
    loss_threshold: float,
):
    try:
        order_id = order_info["order_id"]
        buy_price = order_info["buy_price"]
        user_order_number = order_info.get("user_order_number")
        if order_info.get("notified") is None:
            order_info["notified"] = False

        order_status = trade_client.query_order(symbol, options={"orderId": order_id})
        handle_mexc_response(order_status, "Проверка ордера")
        status = order_status.get("status")

        if status == "CANCELED":
            deal = await sync_to_async(Deal.objects.get)(order_id=order_id)
            deal.status = "CANCELED"
            deal.updated_at = timezone.now()
            await sync_to_async(deal.save)()

            await message.answer(
                f"❌ *СДЕЛКА {user_order_number} ОТМЕНЕНА*\n\n"
                f"📦 Кол-во: `{deal.quantity:.4f}` {deal.symbol[:3]}\n"
                f"💰 Куплено по: `{deal.buy_price:.6f}` {deal.symbol[3:]}\n"
                f"📈 Продажа: `{deal.quantity:.4f}` {deal.symbol[:3]} по {deal.sell_price:.6f} {deal.symbol[3:]}\n",
                parse_mode="Markdown"
            )
            return "CANCELED"
        
        if status == "FILLED":
            deal = await sync_to_async(Deal.objects.get)(order_id=order_id)
            deal.status = "FILLED"
            deal.updated_at = timezone.now()
            await sync_to_async(deal.save)()

            total_received = Decimal(order_status.get("cummulativeQuoteQty", 0))
            quantity = Decimal(order_status.get("executedQty", 0))
            sell_price = total_received / quantity if quantity else 0
            profit = total_received - (deal.buy_price * quantity)

            await message.answer(
                f"✅ *СДЕЛКА {user_order_number} ЗАВЕРШЕНА*\n\n"
                f"📦 Кол-во: `{quantity:.4f}` {symbol[:3]}\n"
                f"💰 Продано по: `{sell_price:.6f}` {symbol[3:]}\n"
                f"📊 Прибыль: `{profit:.2f}` {symbol[3:]}",
                parse_mode="Markdown"
            )
            return "FILLED"

        # Уведомление при падении цены
        price_data = trade_client.ticker_price(symbol)
        handle_mexc_response(price_data, "Проверка цены")
        current_price = float(price_data["price"])
        drop_percent = ((buy_price - current_price) / buy_price) * 100
        logger.info(f"Падение цены для ордера {order_id}: {drop_percent:.2f}%")

        if drop_percent >= loss_threshold and not order_info["notified"]:
            await message.answer(
                f"⚠️ *Падение цены по активному ордеру*\n\n"
                f"📉 Текущая цена: `{current_price:.6f}` {symbol[3:]}\n"
                f"🔻 Падение: `{drop_percent:.2f}%`\n",
                parse_mode="Markdown"
            )
            order_info["notified"] = True

        return "ACTIVE"

    except asyncio.CancelledError:
        return "CANCELLED"
    except Exception as e:
        logger.error(f"Ошибка мониторинга ордера {order_id}: {e}")
        await message.answer(f"⚠️ Ошибка при проверке ордера {order_id}: {e}")
        return "ACTIVE"
