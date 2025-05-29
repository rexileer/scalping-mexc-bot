import asyncio
from aiogram.types import Message
from asgiref.sync import sync_to_async
from django.utils import timezone
from users.models import Deal, User
from subscriptions.models import Subscription
from bot.utils.user_autobuy_tasks import user_autobuy_tasks
from bot.utils.mexc import handle_mexc_response
from bot.utils.api_errors import parse_mexc_error
from mexc_sdk import Trade
from logger import logger
from decimal import Decimal
from bot.constants import MAX_FAILS

async def autobuy_loop(message: Message, telegram_id: int):
    startup_fail_count = 0

    while startup_fail_count < MAX_FAILS:
        try:
            user = await sync_to_async(User.objects.get)(telegram_id=telegram_id)
            trade_client = Trade(api_key=user.api_key, api_secret=user.api_secret)
            symbol = user.pair.replace("/", "")

            active_orders = []
            last_buy_price = None
            fail_count = 0

            while True:
                try:
                    # Проверка подписки
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
                    user = await sync_to_async(User.objects.get)(telegram_id=telegram_id)
                    buy_amount = float(user.buy_amount)
                    profit_percent = float(user.profit)
                    loss_threshold = float(user.loss)
                    # Получение текущей цены
                    ticker_data = trade_client.ticker_price(symbol)
                    handle_mexc_response(ticker_data, "Получение цены")
                    current_price = float(ticker_data["price"])

                    # Проверка условий для покупки
                    price_dropped = last_buy_price and ((last_buy_price - current_price) / last_buy_price * 100) >= loss_threshold
                    price_rose = last_buy_price and ((current_price - last_buy_price) / last_buy_price * 100) >= profit_percent

                    if not last_buy_price or price_dropped or price_rose:
                        if price_rose:
                            rise_percent = (current_price - last_buy_price) / last_buy_price * 100
                            await message.answer(
                                f"⚠️ *Обнаружен рост цены*\n\n"
                                f"🟢 Цена выросла на `{rise_percent:.2f}%` от покупки по `{last_buy_price:.6f}` {symbol[3:]}\n",
                                parse_mode="Markdown"
                            )
                            await asyncio.sleep(user.pause)  # Пауза перед покупкой на росте
                        if price_dropped:
                            drop_percent = (last_buy_price - current_price) / last_buy_price * 100
                            await message.answer(
                                f"⚠️ *Обнаружено падение цены*\n\n"
                                f"🔻 Цена снизилась на `{drop_percent:.2f}%` от покупки по `{last_buy_price:.6f}` {symbol[3:]}\n",
                                parse_mode="Markdown"
                            )
                        buy_order = trade_client.new_order(symbol, "BUY", "MARKET", {"quoteOrderQty": buy_amount})
                        handle_mexc_response(buy_order, "Покупка")
                        order_id = buy_order["orderId"]

                        # Подтягиваем детали ордера
                        order_info = trade_client.query_order(symbol, {"orderId": order_id})
                        logger.info(f"Детали ордера {order_id}: {order_info}")

                        executed_qty = float(order_info.get("executedQty", 0))
                        if executed_qty == 0:
                            await message.answer("❗ Ошибка при создании ордера (executedQty=0).")
                            return

                        spent = float(order_info["cummulativeQuoteQty"])
                        if spent == 0:
                            await message.answer("❗ Ошибка при создании ордера (spent=0).")
                            return
                        
                        real_price = spent / executed_qty if executed_qty > 0 else 0
                        
                        # Расчёт цены продажи
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
                        last_number = await sync_to_async(Deal.objects.filter(user=user).count)()
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
                            f"📦 Кол-во: `{executed_qty:.6f}` {symbol[:3]}\n"
                            f"💸 Потрачено: `{spent:.2f}` {symbol[3:]}\n\n"
                            f"📈 Лимит на продажу: `{sell_price:.6f}` {symbol[3:]}",
                            parse_mode="Markdown"
                        )

                    # Проверка активных ордеров
                    still_active = []
                    orders_changed = False
                    for sell_order_info in active_orders:
                        result = await monitor_order_autobuy(
                            message=message,
                            trade_client=trade_client,
                            symbol=symbol,
                            order_info=sell_order_info,
                        )
                        if result == "ACTIVE":
                            still_active.append(sell_order_info)
                        else:
                            orders_changed = True
                            
                    active_orders = still_active
                    
                    # Обновление last_buy_price
                    if orders_changed:
                        if active_orders:
                            most_recent_order = max(active_orders, key=lambda x: x.get("user_order_number", 0))
                            last_buy_price = most_recent_order["buy_price"]
                            logger.info(f"Updated last_buy_price to {last_buy_price} from order #{most_recent_order['user_order_number']}")
                        else:
                            last_buy_price = None
                            logger.info("Reset last_buy_price to None as no active orders remain")
                            
                    # Интервалы между проверками
                    short_check_interval = 2  # сек — частота проверки активных ордеров

                    if not active_orders:
                        last_buy_price = None
                        logger.info(f"Пауза автобая для юзера {telegram_id}: {user.pause} секунд ")
                        await asyncio.sleep(user.pause)
                    await asyncio.sleep(short_check_interval if active_orders else user.pause)

                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    logger.error(f"Ошибка в autobuy_loop для {telegram_id}, пауза автобая 30 секунд: {e}")
                    fail_count += 1
                    if fail_count >= MAX_FAILS:
                        error_message = parse_mexc_error(e)
                        await message.answer(f"⛔ {error_message}\n\n  Автобай остановлен.")
                        user.autobuy = False
                        await sync_to_async(user.save)()
                        task = user_autobuy_tasks.get(telegram_id)
                        if task:
                            task.cancel()
                            del user_autobuy_tasks[telegram_id]
                        break
                    await asyncio.sleep(30)
            break

        except asyncio.CancelledError:
            logger.info(f"Автобай для {telegram_id} был остановлен вручную.")
            user = await sync_to_async(User.objects.get)(telegram_id=telegram_id)
            user.autobuy = False
            await sync_to_async(user.save)()
            task = user_autobuy_tasks.get(telegram_id)
            if task:
                task.cancel()
                del user_autobuy_tasks[telegram_id]
            raise

        except Exception as e:
            startup_fail_count += 1
            logger.error(f"Ошибка в autobuy_loop при запуске для {telegram_id}: {e}")
            await asyncio.sleep(5)
    else:
        logger.error(f"Автобай не удалось запустить для {telegram_id} после {MAX_FAILS} попыток.")
        user = await sync_to_async(User.objects.get)(telegram_id=telegram_id)
        user.autobuy = False
        await sync_to_async(user.save)()
        task = user_autobuy_tasks.get(telegram_id)
        if task:
            task.cancel()
            del user_autobuy_tasks[telegram_id]



async def monitor_order_autobuy(
    message: Message,
    trade_client: Trade,
    symbol: str,
    order_info: dict,
    max_retries: int = 5,
    retry_delay: int = 5,
):
    order_id = order_info["order_id"]
    buy_price = order_info["buy_price"]
    user_order_number = order_info.get("user_order_number")

    if order_info.get("notified") is None:
        order_info["notified"] = False

    for attempt in range(1, max_retries + 1):
        try:
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
                    f"📦 Кол-во: `{deal.quantity:.6f}` {deal.symbol[:3]}\n"
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
                    f"📦 Кол-во: `{quantity:.6f}` {symbol[:3]}\n"
                    f"💰 Продано по: `{sell_price:.6f}` {symbol[3:]}\n"
                    f"📊 Прибыль: `{profit:.2f}` {symbol[3:]}",
                    parse_mode="Markdown"
                )
                return "FILLED"

            return "ACTIVE"

        except asyncio.CancelledError:
            return "CANCELLED"
        except Exception as e:
            logger.warning(f"Попытка {attempt}/{max_retries} — ошибка мониторинга ордера {order_id}: {e}")
            if attempt < max_retries:
                logger.error(f"Ошибка при получении статуса ордера {order_id}: {e}. Повтор через {retry_delay} секунд.")
                await asyncio.sleep(retry_delay)
            else:
                logger.error(f"Не удалось получить статус ордера {order_id} после {max_retries} попыток")
                error_message = parse_mexc_error(e)
                user_message = f"❌ {error_message}"
                await message.answer(f"⚠️ Ошибка при проверке ордера {user_order_number}:")
                await message.answer(user_message)
                return "ACTIVE"
