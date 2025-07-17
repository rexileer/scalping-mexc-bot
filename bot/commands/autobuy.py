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
import json
import time
import weakref
import gc

# Словарь для хранения состояния autobuy для каждого пользователя
autobuy_states = {}  # {user_id: {'last_buy_price': float, 'active_orders': [], etc.}}

async def autobuy_loop(message: Message, telegram_id: int):
    startup_fail_count = 0

    # Используем lock для предотвращения одновременных закупок
    buy_lock = asyncio.Lock()

    # Глобальная сессия для всех запросов пользователя
    session = None

    while startup_fail_count < MAX_FAILS:
        try:
            # Импортируем websocket_manager внутри функции
            from bot.utils.websocket_manager import websocket_manager

            user = await sync_to_async(User.objects.get)(telegram_id=telegram_id)
            trade_client = Trade(api_key=user.api_key, api_secret=user.api_secret)
            symbol = user.pair.replace("/", "")

            # Инициализируем состояние для пользователя, если его еще нет
            if telegram_id not in autobuy_states:
                autobuy_states[telegram_id] = {
                    'active_orders': [],
                    'last_buy_price': None,
                    'current_price': None,
                    'price_callbacks': [],
                    'last_trade_time': 0,
                    'is_ready': False,
                    'waiting_for_opportunity': False,  # Флаг ожидания новой возможности
                    'restart_after': 0,  # Временная метка для возобновления покупок
                    'waiting_reported': False,  # Флаг для отслеживания, сообщили ли мы о том, что ожидаем
                    'consecutive_errors': 0,  # Счетчик последовательных ошибок
                    'last_drop_notification': 0,  # Время последнего уведомления о падении
                    'last_rise_notification': 0,  # Время последнего уведомления о росте
                    'last_buy_success_time': 0,  # Время последней успешной покупки
                    'last_order_filled_time': 0  # Время последнего завершения сделки
                }

            # Восстанавливаем активные ордера из БД
            deals_qs = Deal.objects.filter(
                user=user,
                status__in=["SELL_ORDER_PLACED", "NEW", "PARTIALLY_FILLED"],
                is_autobuy=True
            ).order_by("-created_at")

            active_deals = await sync_to_async(list)(deals_qs)

            # Заполняем активные ордера
            active_orders = []
            for deal in active_deals:
                active_orders.append({
                    "order_id": deal.order_id,
                    "buy_price": float(deal.buy_price),
                    "notified": False,
                    "user_order_number": deal.user_order_number,
                })

            autobuy_states[telegram_id]['active_orders'] = active_orders

            # Если есть активные ордера, устанавливаем last_buy_price на основе последнего
            if active_orders:
                most_recent_order = max(active_orders, key=lambda x: x.get("user_order_number", 0))
                autobuy_states[telegram_id]['last_buy_price'] = most_recent_order["buy_price"]
                logger.info(f"Установлена цена последней покупки: {most_recent_order['buy_price']} для пользователя {telegram_id}")

            # Проверяем, есть ли соединение с WebSocket для рыночных данных
            if not websocket_manager.market_connection:
                await websocket_manager.connect_market_data()
                logger.info(f"Установлено соединение с WebSocket для рыночных данных")

            # Убедимся, что мы подписаны на обновления цены этой пары
            if symbol not in websocket_manager.market_subscriptions:
                await websocket_manager.subscribe_market_data([symbol])
                logger.info(f"Подписались на данные рынка для {symbol}")

            # Регистрируем колбэк для обновления цены
            async def update_price_for_autobuy(symbol_name, price_str):
                # ДОБАВЛЕНО: Логирование цены при каждом обновлении
                logger.info(f"Price update for {symbol_name}: {price_str}")
                try:
                    # Проверяем, что пользователь все еще в режиме автобай
                    user_data = await sync_to_async(User.objects.filter(telegram_id=telegram_id, autobuy=True).exists)()
                    if not user_data:
                        return

                    price = float(price_str)
                    autobuy_states[telegram_id]['current_price'] = price

                    # Получаем актуальные настройки пользователя из БД при каждом обновлении цены
                    user_settings = await sync_to_async(User.objects.get)(telegram_id=telegram_id)
                    loss_threshold = float(user_settings.loss)
                    profit_percent = float(user_settings.profit)
                    pause_seconds = user_settings.pause # Изменено: просто сохраняем паузу
                    symbol_base = symbol_name[:3] if len(symbol_name) > 3 else symbol_name
                    symbol_quote = symbol_name[3:] if len(symbol_name) > 3 else "QUOTE"

                    # Расширенное логирование для отладки
                    log_prefix = f"Autobuy {telegram_id} ({symbol_name}):"
                    current_price_log = f"Price={price:.6f} {symbol_quote}"
                    last_buy_price_val = autobuy_states[telegram_id]['last_buy_price']
                    last_buy_price_log = f"LastBuy={last_buy_price_val:.6f} {symbol_quote}" if last_buy_price_val is not None else "LastBuy=None"
                    threshold_log = f"LossThr={loss_threshold:.2f}%, ProfitThr={profit_percent:.2f}%, PauseOnRise={pause_seconds}s"
                    is_ready_log = autobuy_states[telegram_id].get('is_ready', False)
                    waiting_opportunity_log = autobuy_states[telegram_id].get('waiting_for_opportunity', False)
                    active_orders_count = len(autobuy_states[telegram_id]['active_orders'])
                    state_log = f"Ready={is_ready_log}, WaitingOpp={waiting_opportunity_log}, BuyLock={buy_lock.locked()}, ActiveOrders={active_orders_count}"
                    logger.info(f"{log_prefix} Update - {current_price_log}, {last_buy_price_log}, {threshold_log}, {state_log}")

                    if not is_ready_log:
                        logger.debug(f"{log_prefix} System not ready. Skipping price processing.")
                        return

                    if buy_lock.locked():
                        logger.debug(f"{log_prefix} Buy operation in progress (lock active). Skipping further processing.")
                        return

                    current_time = time.time()
                    restart_after = autobuy_states[telegram_id].get('restart_after', 0)

                    if waiting_opportunity_log and restart_after > 0:
                        if current_time < restart_after:
                            if not autobuy_states[telegram_id].get('waiting_reported', False):
                                wait_time = restart_after - current_time
                                logger.info(f"{log_prefix} Waiting for new buy opportunity. Time left: {wait_time:.1f}s.")
                                autobuy_states[telegram_id]['waiting_reported'] = True
                            return
                        else:
                            autobuy_states[telegram_id]['restart_after'] = 0
                            autobuy_states[telegram_id]['waiting_for_opportunity'] = False
                            autobuy_states[telegram_id]['waiting_reported'] = False
                            logger.info(f"{log_prefix} Wait period ended. Triggering 'after_waiting_period' buy. Current Price: {price:.6f} {symbol_quote}")
                            asyncio.create_task(process_buy(telegram_id, "after_waiting_period", message, user_settings))
                            return

                    last_buy_price = autobuy_states[telegram_id]['last_buy_price']

                    # Если нет цены последней покупки и не в режиме ожидания - начинаем новый цикл (первая покупка или рестарт)
                    if last_buy_price is None and not waiting_opportunity_log:
                        logger.info(f"{log_prefix} Starting new buy cycle (no last_buy_price, not waiting). Price={price:.6f} {symbol_quote}")
                        asyncio.create_task(process_buy(telegram_id, "new_buy_cycle", message, user_settings))
                        return

                    # Основная логика покупок на росте/падении, если есть цена последней покупки
                    if last_buy_price is not None:
                        price_drop_percent = ((last_buy_price - price) / last_buy_price * 100) if last_buy_price > 0 else 0

                        # Проверяем, не отправлялось ли недавно уведомление о падении
                        last_drop_notification = autobuy_states[telegram_id].get('last_drop_notification', 0)

                        if price_drop_percent >= loss_threshold and (current_time - last_drop_notification) > 10:
                            # Обновляем время последнего уведомления
                            autobuy_states[telegram_id]['last_drop_notification'] = current_time

                            logger.info(f"{log_prefix} Price drop condition met ({price_drop_percent:.2f}% >= {loss_threshold:.2f}%). LastBuy={last_buy_price:.6f}, Current={price:.6f} {symbol_quote}. Triggering 'price_drop' buy.")
                            await message.answer(
                                f"⚠️ *Обнаружено падение цены для {symbol_name}*\n\n"
                                f"🔻 Цена (`{price:.6f} {symbol_quote}`) снизилась на `{price_drop_percent:.2f}%` от покупки по `{last_buy_price:.6f} {symbol_quote}`. \n"
                                f"Покупаем по условию падения ({loss_threshold:.2f}%).",
                                parse_mode="Markdown"
                            )
                            asyncio.create_task(process_buy(telegram_id, "price_drop", message, user_settings))
                            return

                        price_rise_percent = ((price - last_buy_price) / last_buy_price * 100) if last_buy_price > 0 else 0

                        # Проверяем, не отправлялось ли недавно уведомление о росте
                        last_rise_notification = autobuy_states[telegram_id].get('last_rise_notification', 0)

                        # ДОБАВЛЕНО: Логирование рассчитанного процента роста перед проверкой условия
                        logger.info(f"{log_prefix} Calculated price_rise_percent = {price_rise_percent:.4f}% (Price: {price:.6f}, LastBuy: {last_buy_price:.6f})")

                        if price_rise_percent >= profit_percent and (current_time - last_rise_notification) > 10:
                            # Обновляем время последнего уведомления
                            autobuy_states[telegram_id]['last_rise_notification'] = current_time

                            logger.info(f"{log_prefix} Price rise condition met ({price_rise_percent:.2f}% >= {profit_percent:.2f}%). LastBuy={last_buy_price:.6f}, Current={price:.6f} {symbol_quote}. Triggering 'price_rise' buy.")
                            # await message.answer(
                            #     f"⚠️ *Обнаружен рост цены для {symbol_name}*\n\n"
                            #     f"🟢 Цена (`{price:.6f} {symbol_quote}`) выросла на `{price_rise_percent:.2f}%` от покупки по `{last_buy_price:.6f} {symbol_quote}`. \n"
                            #     f"Покупаем по условию роста ({profit_percent:.2f}%).",
                            #     parse_mode="Markdown"
                            # )
                            asyncio.create_task(process_buy(telegram_id, "price_rise", message, user_settings))
                            return

                except Exception as e:
                    logger.error(f"Ошибка в обработчике цены autobuy для {telegram_id} ({symbol_name}): {e}", exc_info=True)

            # Сохраняем колбэк и регистрируем его
            autobuy_states[telegram_id]['price_callbacks'].append(update_price_for_autobuy)
            await websocket_manager.register_price_callback(symbol, update_price_for_autobuy)

            # Получаем текущую цену через REST API для начала
            ticker_data = trade_client.ticker_price(symbol)
            handle_mexc_response(ticker_data, "Получение цены")
            current_price = float(ticker_data["price"])
            autobuy_states[telegram_id]['current_price'] = current_price
            logger.info(f"Получена начальная цена для {telegram_id}: {current_price}")

            # Отмечаем, что система готова обрабатывать обновления
            autobuy_states[telegram_id]['is_ready'] = True

            # Если нет активных ордеров и есть начальная цена, делаем первую покупку
            if not active_orders and current_price > 0:
                logger.info(f"Запускаем первую покупку для {telegram_id} по цене {current_price}")
                await process_buy(telegram_id, "initial_purchase", message, user)

            # Планируем задачу проверки ресурсов
            asyncio.create_task(periodic_resource_check(telegram_id))

            # Сообщаем пользователю, что автобай активирован
            await message.answer(
                f"✅ *Автобай активирован*\n\n"
                f"📊 Текущая цена: `{current_price:.6f}` {symbol[3:]}\n"
                f"💰 Сумма закупки: `{user.buy_amount}` {symbol[3:]}\n"
                f"📈 Профит: `{user.profit}%`\n"
                f"📉 Падение: `{user.loss}%`\n"
                f"⏱️ Пауза: `{user.pause}` сек\n",
                parse_mode="Markdown"
            )

            # Ждем завершения автобая или отмены задачи
            while True:
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

                # Проверяем, не нужно ли начать новую покупку после периода ожидания
                current_time = time.time()
                restart_after = autobuy_states[telegram_id].get('restart_after', 0)
                waiting_for_opportunity = autobuy_states[telegram_id].get('waiting_for_opportunity', False)

                if waiting_for_opportunity and restart_after > 0 and current_time >= restart_after:
                    # Время ожидания истекло, запускаем новую покупку
                    autobuy_states[telegram_id]['restart_after'] = 0
                    autobuy_states[telegram_id]['waiting_for_opportunity'] = False
                    autobuy_states[telegram_id]['waiting_reported'] = False
                    logger.info(f"Период ожидания после закрытия сделки истек для {telegram_id} (проверка в основном цикле)")

                    # Запускаем новую покупку, если нет активных ордеров
                    if not autobuy_states[telegram_id]['active_orders']:
                        # await message.answer(f"🔄 Возобновляем автобай после паузы (основной цикл). Текущая цена: {autobuy_states[telegram_id]['current_price']}")
                        await process_buy(telegram_id, "after_waiting_period_main_loop", message, user)

                # Просто ждем, реальная работа происходит в колбэках
                await asyncio.sleep(10)  # Проверка подписки и состояния каждые 10 секунд

            break  # Выход из внешнего цикла

        except asyncio.CancelledError:
            logger.info(f"Задача автобая для {telegram_id} была отменена")
            # Очищаем ресурсы
            if telegram_id in autobuy_states:
                # Импортируем websocket_manager внутри блока
                from bot.utils.websocket_manager import websocket_manager

                for callback in autobuy_states[telegram_id]['price_callbacks']:
                    try:
                        user = await sync_to_async(User.objects.get)(telegram_id=telegram_id)
                        symbol_to_unregister = user.pair.replace("/", "")
                        if symbol_to_unregister in websocket_manager.price_callbacks:
                            if callback in websocket_manager.price_callbacks[symbol_to_unregister]:
                                websocket_manager.price_callbacks[symbol_to_unregister].remove(callback)
                    except Exception as e:
                        logger.error(f"Ошибка при очистке колбэков для {telegram_id}: {e}")

            # Если есть сессия, закрываем её
            if session:
                try:
                    await session.close()
                except Exception as e:
                    logger.error(f"Ошибка при закрытии сессии: {e}")

            raise

        except Exception as e:
            logger.error(f"Ошибка в autobuy_loop для {telegram_id}, пауза автобая 30 секунд: {e}")
            startup_fail_count += 1
            if startup_fail_count >= MAX_FAILS:
                error_message = parse_mexc_error(e)
                await message.answer(f"⛔ {error_message}\n\n  Автобай остановлен.")
                user.autobuy = False
                await sync_to_async(user.save)()
                task = user_autobuy_tasks.get(telegram_id)
                if task:
                    task.cancel()
                    del user_autobuy_tasks[telegram_id]

                # Удаляем колбэки и состояние
                if telegram_id in autobuy_states:
                    # Импортируем websocket_manager внутри блока
                    from bot.utils.websocket_manager import websocket_manager

                    for callback in autobuy_states[telegram_id]['price_callbacks']:
                        try:
                            symbol_to_unregister = user.pair.replace("/", "")
                            if symbol_to_unregister in websocket_manager.price_callbacks:
                                if callback in websocket_manager.price_callbacks[symbol_to_unregister]:
                                    websocket_manager.price_callbacks[symbol_to_unregister].remove(callback)
                        except Exception as cleanup_error:
                            logger.error(f"Ошибка при очистке колбэков: {cleanup_error}")
                    del autobuy_states[telegram_id]

                # Если есть сессия, закрываем её
                if session:
                    try:
                        await session.close()
                    except Exception as se:
                        logger.error(f"Ошибка при закрытии сессии: {se}")

                break
            await asyncio.sleep(30)
    else:
        logger.error(f"Автобай не удалось запустить для {telegram_id} после {MAX_FAILS} попыток.")
        user = await sync_to_async(User.objects.get)(telegram_id=telegram_id)
        user.autobuy = False
        await sync_to_async(user.save)()
        task = user_autobuy_tasks.get(telegram_id)
        if task:
            task.cancel()
            del user_autobuy_tasks[telegram_id]


async def process_buy(telegram_id: int, reason: str, message: Message, user: User):
    """Обработка покупки с защитой от одновременных операций"""
    # Импортируем здесь для избежания циклических импортов
    from bot.utils.websocket_manager import websocket_manager

    # Получаем актуальные настройки пользователя из БД
    user = await sync_to_async(User.objects.get)(telegram_id=telegram_id)

    # Используем Lock для предотвращения множественных покупок одновременно
    lock = asyncio.Lock()

    if not await lock.acquire():
        logger.warning(f"Не удалось получить блокировку для покупки - {telegram_id}")
        return

    try:
        # Еще раз проверяем, что пользователь все еще в режиме автобай
        user_active = await sync_to_async(User.objects.filter(telegram_id=telegram_id, autobuy=True).exists)()
        if not user_active:
            logger.info(f"Отмена покупки - пользователь {telegram_id} больше не в режиме автобай")
            return

        # Помечаем время последней операции
        autobuy_states[telegram_id]['last_trade_time'] = time.time()

        # Сбрасываем флаги ожидания
        autobuy_states[telegram_id]['waiting_for_opportunity'] = False
        autobuy_states[telegram_id]['restart_after'] = 0
        autobuy_states[telegram_id]['waiting_reported'] = False

        # Получаем текущие данные - ВСЕГДА свежие из БД
        client_session = None

        # Счетчик последовательных ошибок
        consecutive_errors = autobuy_states[telegram_id].get('consecutive_errors', 0)

        try:
            # Отправляем сообщение о начале покупки для лучшей обратной связи
            if reason == "after_waiting_period":
                symbol = user.pair.replace("/", "")
                current_price = autobuy_states[telegram_id].get('current_price', 0)
                # await message.answer(f"🔄 Возобновляем автобай для {symbol} после паузы. Текущая цена: {current_price:.6f} {symbol[3:]}")

            trade_client = Trade(api_key=user.api_key, api_secret=user.api_secret)
            symbol = user.pair.replace("/", "")
            buy_amount = float(user.buy_amount)
            profit_percent = float(user.profit)
            pause_seconds = user.pause  # Для использования после покупки

            # Логируем начало покупки
            logger.info(f"Начинаем покупку для {telegram_id}, причина: {reason}")

            # Выполняем покупку
            buy_order = trade_client.new_order(symbol, "BUY", "MARKET", {"quoteOrderQty": buy_amount})
            handle_mexc_response(buy_order, "Покупка")
            order_id = buy_order["orderId"]

            # Подтягиваем детали ордера
            order_info = trade_client.query_order(symbol, {"orderId": order_id})
            logger.info(f"Детали ордера {order_id}: {order_info}")

            executed_qty = float(order_info.get("executedQty", 0))
            if executed_qty == 0:
                await message.answer("❗ Ошибка при создании ордера (executedQty=0).")
                autobuy_states[telegram_id]['consecutive_errors'] = consecutive_errors + 1
                if autobuy_states[telegram_id]['consecutive_errors'] >= 3:
                    user.autobuy = False
                    await sync_to_async(user.save)()
                    await message.answer("⛔ Автобай остановлен после 3 последовательных ошибок при создании ордеров.")
                return

            spent = float(order_info["cummulativeQuoteQty"])
            if spent == 0:
                await message.answer("❗ Ошибка при создании ордера (spent=0).")
                autobuy_states[telegram_id]['consecutive_errors'] = consecutive_errors + 1
                if autobuy_states[telegram_id]['consecutive_errors'] >= 3:
                    user.autobuy = False
                    await sync_to_async(user.save)()
                    await message.answer("⛔ Автобай остановлен после 3 последовательных ошибок при создании ордеров.")
                return

            # Сбрасываем счетчик ошибок при успешной покупке
            autobuy_states[telegram_id]['consecutive_errors'] = 0

            real_price = spent / executed_qty if executed_qty > 0 else 0

            # Сохраняем новую цену последней покупки сразу
            autobuy_states[telegram_id]['last_buy_price'] = real_price

            # Логируем причину покупки
            logger.info(f"Buy triggered for {telegram_id} because of {reason}. New last_buy_price: {real_price}")

            # Расчёт цены продажи - всегда используем актуальный профит из БД
            user_settings = await sync_to_async(User.objects.get)(telegram_id=telegram_id)
            profit_percent = float(user_settings.profit)
            sell_price = round(real_price * (1 + profit_percent / 100), 6)

            # Создание лимитного ордера на продажу
            sell_order = trade_client.new_order(symbol, "SELL", "LIMIT", {
                "quantity": executed_qty,
                "price": f"{sell_price:.6f}",
                "timeInForce": "GTC"
            })
            handle_mexc_response(sell_order, "Продажа")
            sell_order_id = sell_order["orderId"]
            logger.info(f"SELL ордер {sell_order_id} выставлен на {sell_price:.6f} {symbol[3:]}")

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

            # Добавляем ордер в список активных
            order_info = {
                "order_id": sell_order_id,
                "buy_price": real_price,
                "notified": False,
                "user_order_number": user_order_number,
            }

            # Получаем актуальный список активных ордеров
            active_orders = autobuy_states[telegram_id]['active_orders']
            active_orders.append(order_info)
            autobuy_states[telegram_id]['active_orders'] = active_orders

            # Отправляем сообщение об открытии сделки
            await message.answer(
                f"🟢 *СДЕЛКА {user_order_number} ОТКРЫТА*\n\n"
                f"📉 Куплено по: `{real_price:.6f}` {symbol[3:]}\n"
                f"📦 Кол-во: `{executed_qty:.6f}` {symbol[:3]}\n"
                f"💸 Потрачено: `{spent:.2f}` {symbol[3:]}\n\n"
                f"📈 Лимит на продажу: `{sell_price:.6f}` {symbol[3:]}\n",
                parse_mode="Markdown"
            )

            # Если это была покупка на росте, устанавливаем паузу ПОСЛЕ покупки
            if reason == "price_rise" and pause_seconds > 0:
                # Устанавливаем время возобновления после паузы
                autobuy_states[telegram_id]['waiting_for_opportunity'] = True
                autobuy_states[telegram_id]['restart_after'] = time.time() + pause_seconds
                logger.info(f"Установлена пауза {pause_seconds}с после покупки на росте для {telegram_id}")

        except Exception as e:
            logger.error(f"Ошибка в процессе выполнения покупки для {telegram_id}: {e}")
            error_message = parse_mexc_error(e)
            await message.answer(f"❌ Ошибка при покупке: {error_message}")

            # Увеличиваем счетчик последовательных ошибок
            autobuy_states[telegram_id]['consecutive_errors'] = consecutive_errors + 1

            # Если достигли 3 последовательных ошибки, останавливаем автобай
            if autobuy_states[telegram_id]['consecutive_errors'] >= 3:
                user.autobuy = False
                await sync_to_async(user.save)()
                await message.answer("⛔ Автобай остановлен после 3 последовательных ошибок. Проверьте настройки и баланс.")
                logger.warning(f"Автобай остановлен для {telegram_id} после 3 последовательных ошибок")

        finally:
            # Закрываем сессию, если она была создана
            if client_session:
                try:
                    await client_session.close()
                except Exception as e:
                    logger.error(f"Ошибка при закрытии сессии: {e}")
    except Exception as e:
        logger.error(f"Ошибка при выполнении покупки для {telegram_id}: {e}")
        error_message = parse_mexc_error(e)
        await message.answer(f"❌ Ошибка при покупке: {error_message}")
    finally:
        # Всегда освобождаем блокировку
        lock.release()


# Обработка обновлений ордеров autobuy через WebSocket
async def process_order_update_for_autobuy(order_id, symbol, status, user_id):
    """Обработка обновлений ордеров для автобая через WebSocket"""
    if user_id not in autobuy_states:
        logger.debug(f"[AutobuyOrderUpdate] User {user_id} not in autobuy_states. Skipping.")
        return

    # Отладочный лог с полным состоянием
    logger.info(f"[AutobuyOrderUpdate] User {user_id}: Processing order_id={order_id}, symbol={symbol}, status={status}. Current Autobuy State: {autobuy_states[user_id]}")

    active_orders = autobuy_states[user_id]['active_orders']
    old_last_buy_price = autobuy_states[user_id].get('last_buy_price')

    # Ищем ордер среди активных
    order_index = next((i for i, order in enumerate(active_orders) if order["order_id"] == order_id), None)

    if order_index is not None:
        logger.info(f"[AutobuyOrderUpdate] User {user_id}: Found order {order_id} in active_orders at index {order_index}. Current active_orders: {active_orders}")
        if status in ["FILLED", "CANCELED"]:
            # Получаем информацию о завершенном ордере
            order_info = active_orders[order_index]
            logger.info(f"[AutobuyOrderUpdate] User {user_id}: Order {order_id} (UserOrderNum: {order_info.get('user_order_number')}) has status {status}. Removing from active_orders.")

            # Если ордер исполнен или отменен, удаляем его из активных
            active_orders.pop(order_index)
            autobuy_states[user_id]['active_orders'] = active_orders
            logger.info(f"[AutobuyOrderUpdate] User {user_id}: active_orders after removal: {autobuy_states[user_id]['active_orders']}")

            # Если не осталось активных ордеров, устанавливаем паузу перед следующей покупкой
            if not active_orders:
                logger.info(f"[AutobuyOrderUpdate] User {user_id}: No active orders remaining.")
                # Получаем пользовательские настройки для определения паузы
                try:
                    user = await sync_to_async(User.objects.get)(telegram_id=user_id)
                    pause_seconds = user.pause

                    # Устанавливаем время следующей возможной покупки
                    autobuy_states[user_id]['last_buy_price'] = None
                    autobuy_states[user_id]['waiting_for_opportunity'] = True
                    autobuy_states[user_id]['restart_after'] = time.time() + pause_seconds
                    autobuy_states[user_id]['waiting_reported'] = False

                    logger.info(f"[AutobuyOrderUpdate] User {user_id}: Reset last_buy_price to None. waiting_for_opportunity=True. Next buy possible after {pause_seconds}s (at {autobuy_states[user_id]['restart_after']}).")
                except Exception as e:
                    logger.error(f"[AutobuyOrderUpdate] User {user_id}: Error getting user settings for pause: {e}")
                    # Если не удалось получить настройки паузы, просто сбрасываем last_buy_price
                    autobuy_states[user_id]['last_buy_price'] = None
                    logger.info(f"[AutobuyOrderUpdate] User {user_id}: Reset last_buy_price to None (error case).")
            else:
                # Иначе устанавливаем last_buy_price по самому свежему ордеру
                most_recent_order = max(active_orders, key=lambda x: x.get("user_order_number", 0))
                autobuy_states[user_id]['last_buy_price'] = most_recent_order["buy_price"]
                logger.info(f"[AutobuyOrderUpdate] User {user_id}: Updated last_buy_price to {most_recent_order['buy_price']} from active order #{most_recent_order['user_order_number']}. Active orders count: {len(active_orders)}")
        else:
            logger.info(f"[AutobuyOrderUpdate] User {user_id}: Order {order_id} status is {status} (not FILLED/CANCELED). No state change.")
    else:
        logger.info(f"[AutobuyOrderUpdate] User {user_id}: Order {order_id} not found in active_orders. Current active_orders: {active_orders}")

    # Лог изменений
    new_last_buy_price = autobuy_states[user_id].get('last_buy_price')
    if old_last_buy_price != new_last_buy_price:
        logger.info(f"[AutobuyOrderUpdate] User {user_id}: last_buy_price changed from {old_last_buy_price} to {new_last_buy_price}.")
    elif status in ["FILLED", "CANCELED"] and order_index is not None:
        logger.info(f"[AutobuyOrderUpdate] User {user_id}: last_buy_price remains {new_last_buy_price} after processing order {order_id} ({status}).")


async def periodic_resource_check(telegram_id: int):
    """Периодическая проверка и очистка ресурсов"""
    while telegram_id in autobuy_states:
        try:
            # Вызываем сборщик мусора
            gc.collect()

            # Журналируем статистику о количестве клиентских сессий
            client_session_count = 0
            for obj in gc.get_objects():
                if 'ClientSession' in str(type(obj)):
                    client_session_count += 1

            if client_session_count > 5:  # Порог для журналирования
                logger.warning(f"Обнаружено {client_session_count} клиентских сессий. Рекомендуется проверить утечку ресурсов.")

            # Проверяем состояние ожидания и обновляем его при необходимости
            current_time = time.time()
            restart_after = autobuy_states[telegram_id].get('restart_after', 0)
            waiting_for_opportunity = autobuy_states[telegram_id].get('waiting_for_opportunity', False)

            if waiting_for_opportunity and restart_after > 0 and current_time >= restart_after:
                logger.info(f"Период ожидания истек для {telegram_id} (проверка ресурсов)")

            # Обновляем параметры пользователя
            from bot.utils.websocket_manager import websocket_manager

            # Проверяем соединение с WebSocket и восстанавливаем при необходимости
            user = await sync_to_async(User.objects.get)(telegram_id=telegram_id)
            symbol = user.pair.replace("/", "")

            if not websocket_manager.market_connection:
                logger.warning(f"Соединение с WebSocket для рынка потеряно, переподключаемся")
                await websocket_manager.connect_market_data()

            if symbol not in websocket_manager.market_subscriptions:
                logger.warning(f"Подписка на {symbol} отсутствует, переподписываемся")
                await websocket_manager.subscribe_market_data([symbol])

        except Exception as e:
            logger.error(f"Ошибка в periodic_resource_check для {telegram_id}: {e}")

        # Проверка каждые 30 секунд
        await asyncio.sleep(30)
