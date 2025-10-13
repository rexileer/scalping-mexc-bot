import asyncio
from aiogram.types import Message
from asgiref.sync import sync_to_async
from django.utils import timezone
from users.models import Deal, User
from subscriptions.models import Subscription
from bot.utils.user_autobuy_tasks import user_autobuy_tasks
from bot.utils.mexc import handle_mexc_response
from bot.utils.api_errors import parse_mexc_error
from bot.utils.mexc_rest import MexcRestClient
from bot.logger import logger
from bot.utils.error_notifier import notify_user_autobuy_error
from decimal import Decimal
from bot.constants import MAX_FAILS
import json
import time
import weakref
import gc

# Словарь для хранения состояния autobuy для каждого пользователя
autobuy_states = {}  # {user_id: {'last_buy_price': float, 'active_orders': [], etc.}}

# Глобальные переменные для отслеживания триггеров
trigger_states = {}  # {user_id: {'trigger_price': float, 'trigger_time': float, 'is_rise_trigger': bool}}

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
            rest = MexcRestClient(api_key=user.api_key, api_secret=user.api_secret)
            symbol = user.pair.replace("/", "")

            # Инициализируем состояние для пользователя, если его еще нет
            if telegram_id not in autobuy_states:
                autobuy_states[telegram_id] = {
                    'active_orders': [],
                    'last_buy_price': None,
                    'current_price': None,
                    'price_callbacks': [],
                    'bookticker_callbacks': [],
                    'last_trade_time': 0,
                    'is_ready': False,
                    'waiting_for_opportunity': False,  # Флаг ожидания новой возможности
                    'restart_after': 0,  # Временная метка для возобновления покупок
                    'waiting_reported': False,  # Флаг для отслеживания, сообщили ли мы о том, что ожидаем
                    'consecutive_errors': 0,  # Счетчик последовательных ошибок
                    'last_drop_notification': 0,  # Время последнего уведомления о падении
                    'last_rise_notification': 0,  # Время последнего уведомления о росте
                    'last_buy_success_time': 0,  # Время последней успешной покупки
                    'last_order_filled_time': 0,  # Время последнего завершения сделки
                    'trigger_price': None,  # Цена триггера для покупок на росте
                    'trigger_time': 0,  # Время установки триггера
                    'trigger_activated_time': 0,  # Время активации триггера (когда цена пересекла триггер)
                    'is_rise_trigger': False,  # Флаг триггера на росте
                    'is_trigger_activated': False,  # Флаг активации триггера
                    'pause_trend_prices': [],  # Список цен во время паузы для анализа тренда
                    'trend_only_rise': True,  # Флаг исключительного роста во время паузы
                    'last_pause_price': None,  # Последняя цена во время паузы
                    'rise_buy_count': 0,  # Счетчик покупок на росте в текущем цикле
                    'last_ask_price': None,  # Последняя ask цена для анализа триггеров
                    'last_mid_price': None,  # Последняя mid цена для анализа тренда
                    'buy_in_progress': False,  # Глобальный флаг покупки
                    'buy_lock': asyncio.Lock(),  # Глобальная блокировка покупки на пользователя
                }

            # Восстанавливаем активные ордера из БД
            deals_qs = Deal.objects.filter(
                user=user,
                status__in=["NEW", "PARTIALLY_FILLED"],
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

            # Подписываемся на bookTicker данные (включает и цены, и bid/ask)
            if symbol not in websocket_manager.bookticker_subscriptions:
                await websocket_manager.subscribe_bookticker_data([symbol])
                logger.info(f"Подписались на bookTicker данные для {symbol}")

            # Регистрируем колбэк для bookTicker данных (заменяет старый колбэк для цен)
            async def update_bookticker_for_autobuy(symbol_name, bid_price, ask_price, bid_qty, ask_qty):
                try:
                    # Проверяем, что пользователь все еще в режиме автобай
                    user_data = await sync_to_async(User.objects.filter(telegram_id=telegram_id, autobuy=True).exists)()
                    if not user_data:
                        return

                    # Получаем информацию о направлении цены
                    direction_info = websocket_manager.get_price_direction(symbol_name)
                    is_rise = direction_info.get('is_rise', False)
                    current_time = time.time()
                    mid_price = (float(bid_price) + float(ask_price)) / 2

                    # Получаем актуальные настройки пользователя
                    user_settings = await sync_to_async(User.objects.get)(telegram_id=telegram_id)
                    loss_threshold = float(user_settings.loss)
                    profit_percent = float(user_settings.profit)
                    pause_seconds = user_settings.pause

                    # Обновляем текущую цену
                    autobuy_states[telegram_id]['current_price'] = mid_price

                    # Логируем обновление bookTicker
                    # logger.info(f"BookTicker update for {telegram_id} ({symbol_name}): bid={bid_price}, ask={ask_price}, mid={mid_price:.6f}, is_rise={is_rise}")

                    # Проверяем триггеры для покупок на росте
                    await check_rise_triggers(telegram_id, symbol_name, float(bid_price), float(ask_price), is_rise, current_time, user_settings)

                    # Проверяем условия для покупок на падении (используем ask цену)
                    last_buy_price = autobuy_states[telegram_id]['last_buy_price']
                    if last_buy_price is not None:
                        ask_price = float(ask_price)
                        price_drop_percent = ((last_buy_price - ask_price) / last_buy_price * 100) if last_buy_price > 0 else 0
                        last_drop_notification = autobuy_states[telegram_id].get('last_drop_notification', 0)

                        if price_drop_percent >= loss_threshold and (current_time - last_drop_notification) > 10:
                            autobuy_states[telegram_id]['last_drop_notification'] = current_time
                            logger.info(f"Price drop condition met for {telegram_id}: ask={ask_price:.6f}, last_buy={last_buy_price:.6f}, drop={price_drop_percent:.2f}% >= {loss_threshold:.2f}%")
                            
                            # Send notification using bot instance directly
                            from bot.config import bot_instance
                            try:
                                await bot_instance.send_message(
                                    telegram_id,
                                    f"🔻 Обнаружено падение цены для {symbol_name}\n\n"
                                    f"🔻 Цена ({ask_price:.6f} USDC) снизилась на {price_drop_percent:.2f}% от покупки по {last_buy_price:.6f} USDC. \n"
                                    f"Покупаем по условию падения ({loss_threshold:.2f}%)."
                                )
                                logger.info(f"Drop notification sent to {telegram_id}")
                            except Exception as e:
                                logger.error(f"Failed to send drop notification to {telegram_id}: {e}")
                            
                            # Перед запуском покупки проверяем очередь в памяти и в БД, а также флаг покупки
                            state = autobuy_states.get(telegram_id, {})
                            if state.get('buy_in_progress'):
                                logger.info(f"Skip price_drop buy: buy_in_progress for {telegram_id}")
                                return

                            # Create a fake message object for process_buy
                            from bot.utils.autobuy_restart import FakeMessage
                            from bot.config import bot_instance
                            fake_message = FakeMessage(telegram_id, bot_instance)
                            logger.info(f"Starting process_buy for {telegram_id} due to price drop")
                            asyncio.create_task(process_buy(telegram_id, "price_drop", fake_message, user_settings))

                except Exception as e:
                    logger.error(f"Ошибка в обработчике bookTicker autobuy для {telegram_id} ({symbol_name}): {e}", exc_info=True)

            # Регистрируем колбэк с WebSocket менеджером
            await websocket_manager.register_bookticker_callback(symbol, update_bookticker_for_autobuy)
            autobuy_states[telegram_id]['bookticker_callbacks'].append(update_bookticker_for_autobuy)
            logger.info(f"Registered bookTicker callback for {telegram_id} on {symbol}")

            # Получаем текущую цену через REST API для начала
            ticker_data = await rest.ticker_price(symbol)
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
                        # Дополнительная проверка в БД на активные сделки autobuy
                        has_active = await sync_to_async(Deal.objects.filter(user=user, is_autobuy=True, status__in=["NEW", "PARTIALLY_FILLED"]).exists)()
                        if has_active:
                            logger.info(f"DB guard: активные сделки обнаружены для {telegram_id}, покупка не запускается")
                        else:
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

                # Clean up price callbacks
                for callback in autobuy_states[telegram_id]['price_callbacks']:
                    try:
                        user = await sync_to_async(User.objects.get)(telegram_id=telegram_id)
                        symbol_to_unregister = user.pair.replace("/", "")
                        if symbol_to_unregister in websocket_manager.price_callbacks:
                            if callback in websocket_manager.price_callbacks[symbol_to_unregister]:
                                websocket_manager.price_callbacks[symbol_to_unregister].remove(callback)
                    except Exception as e:
                        logger.error(f"Ошибка при очистке price колбэков для {telegram_id}: {e}")
                
                # Clean up bookTicker callbacks
                for callback in autobuy_states[telegram_id]['bookticker_callbacks']:
                    try:
                        user = await sync_to_async(User.objects.get)(telegram_id=telegram_id)
                        symbol_to_unregister = user.pair.replace("/", "")
                        await websocket_manager.unregister_bookticker_callback(symbol_to_unregister, callback)
                    except Exception as e:
                        logger.error(f"Ошибка при очистке bookTicker колбэков для {telegram_id}: {e}")

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
                
                # Send additional notification about autobuy stop
                try:
                    from bot.config import bot_instance
                    await bot_instance.send_message(
                        telegram_id,
                        f"⛔ Автобай остановлен после {MAX_FAILS} последовательных ошибок.\n"
                        f"Проверьте настройки и баланс."
                    )
                except Exception as notify_error:
                    logger.error(f"Failed to send autobuy stop notification to {telegram_id}: {notify_error}")

                # Удаляем колбэки и состояние
                if telegram_id in autobuy_states:
                    # Импортируем websocket_manager внутри блока
                    from bot.utils.websocket_manager import websocket_manager

                    # Clean up price callbacks
                    for callback in autobuy_states[telegram_id]['price_callbacks']:
                        try:
                            symbol_to_unregister = user.pair.replace("/", "")
                            if symbol_to_unregister in websocket_manager.price_callbacks:
                                if callback in websocket_manager.price_callbacks[symbol_to_unregister]:
                                    websocket_manager.price_callbacks[symbol_to_unregister].remove(callback)
                        except Exception as cleanup_error:
                            logger.error(f"Ошибка при очистке price колбэков: {cleanup_error}")
                    
                    # Clean up bookTicker callbacks
                    for callback in autobuy_states[telegram_id]['bookticker_callbacks']:
                        try:
                            symbol_to_unregister = user.pair.replace("/", "")
                            await websocket_manager.unregister_bookticker_callback(symbol_to_unregister, callback)
                        except Exception as cleanup_error:
                            logger.error(f"Ошибка при очистке bookTicker колбэков: {cleanup_error}")
                    
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
        
        # Send notification about autobuy failure
        try:
            from bot.config import bot_instance
            await bot_instance.send_message(
                telegram_id,
                f"⛔ Автобай не удалось запустить после {MAX_FAILS} попыток.\n"
                f"Проверьте настройки и попробуйте снова."
            )
        except Exception as notify_error:
            logger.error(f"Failed to send autobuy failure notification to {telegram_id}: {notify_error}")


async def process_buy(telegram_id: int, reason: str, message: Message, user: User):
    """Обработка покупки с защитой от одновременных операций"""
    # Импортируем здесь для избежания циклических импортов
    from bot.utils.websocket_manager import websocket_manager

    logger.info(f"process_buy called for {telegram_id} with reason: {reason}")

    # Получаем актуальные настройки пользователя из БД
    user = await sync_to_async(User.objects.get)(telegram_id=telegram_id)

    # Глобальная защита на пользователя
    state = autobuy_states.get(telegram_id)
    if not state:
        logger.warning(f"No state for user {telegram_id} in process_buy")
        return

    lock = state.get('buy_lock')
    if lock is None:
        lock = asyncio.Lock()
        state['buy_lock'] = lock

    if state.get('buy_in_progress'):
        logger.info(f"Skip process_buy: buy_in_progress for {telegram_id}")
        return

    await lock.acquire()
    state['buy_in_progress'] = True

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

            rest = MexcRestClient(api_key=user.api_key, api_secret=user.api_secret)
            symbol = user.pair.replace("/", "")
            buy_amount = float(user.buy_amount)
            profit_percent = float(user.profit)
            pause_seconds = user.pause  # Для использования после покупки

            # Логируем начало покупки
            logger.info(f"Начинаем покупку для {telegram_id}, причина: {reason}")

            # Выполняем покупку
            buy_order = await rest.new_order(symbol, "BUY", "MARKET", {"quoteOrderQty": buy_amount})
            handle_mexc_response(buy_order, "Покупка")
            order_id = buy_order["orderId"]

            # Подтягиваем детали ордера
            order_info = await rest.query_order(symbol, {"orderId": order_id})
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
            sell_order = await rest.new_order(
                symbol,
                "SELL",
                "LIMIT",
                {
                    "quantity": executed_qty,
                    "price": f"{sell_price:.6f}",
                    "timeInForce": "GTC",
                },
            )
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
                status="NEW",
                is_autobuy=True
            )

            # Уточняем статус сразу после создания SELL через REST
            try:
                order_check = await rest.query_order(symbol, {"orderId": sell_order_id})
                current_status = order_check.get("status")
                if current_status and current_status != "NEW":
                    deal_obj = await sync_to_async(Deal.objects.get)(order_id=sell_order_id)
                    deal_obj.status = current_status
                    await sync_to_async(deal_obj.save)()
            except Exception as e:
                logger.warning(f"[Autobuy] Не удалось уточнить начальный статус ордера {sell_order_id}: {e}")

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
            try:
                from bot.config import bot_instance
                await bot_instance.send_message(
                    telegram_id,
                    f"🟢 *СДЕЛКА {user_order_number} ОТКРЫТА*\n\n"
                    f"📉 Куплено по: `{real_price:.6f}` {symbol[3:]}\n"
                    f"📦 Кол-во: `{executed_qty:.6f}` {symbol[:3]}\n"
                    f"💸 Потрачено: `{spent:.2f}` {symbol[3:]}\n\n"
                    f"📈 Лимит на продажу: `{sell_price:.6f}` {symbol[3:]}\n",
                    parse_mode="Markdown"
                )
            except Exception as e:
                logger.error(f"Failed to send buy notification to {telegram_id}: {e}")
                # Fallback to message.answer if bot_instance fails
                try:
                    await message.answer(
                        f"🟢 *СДЕЛКА {user_order_number} ОТКРЫТА*\n\n"
                        f"📉 Куплено по: `{real_price:.6f}` {symbol[3:]}\n"
                        f"📦 Кол-во: `{executed_qty:.6f}` {symbol[:3]}\n"
                        f"💸 Потрачено: `{spent:.2f}` {symbol[3:]}\n\n"
                        f"📈 Лимит на продажу: `{sell_price:.6f}` {symbol[3:]}\n",
                        parse_mode="Markdown"
                    )
                except Exception as fallback_error:
                    logger.error(f"Failed to send buy notification via fallback to {telegram_id}: {fallback_error}")

            # Устанавливаем триггер для покупок на росте после любой покупки или продажи
            if reason in ["price_rise", "price_drop", "new_buy_cycle", "initial_purchase", "after_waiting_period", "rise_trigger"]:
                # Получаем текущую цену из bookTicker
                bookticker_data = websocket_manager.get_current_bookticker(symbol)
                if bookticker_data:
                    ask_price = float(bookticker_data['ask_price'])  # Используем ask цену
                    current_time = time.time()
                    
                    # Устанавливаем триггер на росте по ask цене
                    autobuy_states[telegram_id]['trigger_price'] = ask_price
                    autobuy_states[telegram_id]['trigger_time'] = current_time
                    autobuy_states[telegram_id]['is_rise_trigger'] = True
                    autobuy_states[telegram_id]['is_trigger_activated'] = False
                    autobuy_states[telegram_id]['trigger_activated_time'] = 0
                    autobuy_states[telegram_id]['pause_trend_prices'] = []
                    autobuy_states[telegram_id]['trend_only_rise'] = True
                    autobuy_states[telegram_id]['last_pause_price'] = None
                    
                    logger.info(f"Rise trigger set for {telegram_id} at ask price {ask_price:.6f} after {reason}")
                else:
                    logger.warning(f"Could not set rise trigger for {telegram_id}: no bookTicker data available")

            # Если это была покупка на росте, устанавливаем паузу ПОСЛЕ покупки
            if reason == "price_rise" and pause_seconds > 0:
                # Устанавливаем время возобновления после паузы
                autobuy_states[telegram_id]['waiting_for_opportunity'] = True
                autobuy_states[telegram_id]['restart_after'] = time.time() + pause_seconds
                logger.info(f"Установлена пауза {pause_seconds}с после покупки на росте для {telegram_id}")

        except Exception as e:
            logger.error(f"Ошибка в процессе выполнения покупки для {telegram_id}: {e}", extra={"user_id": telegram_id})
            error_message = parse_mexc_error(e)
            await message.answer(f"❌ Ошибка при покупке: {error_message}")
            try:
                await notify_user_autobuy_error(telegram_id, "при создании ордера", e)
            except Exception:
                pass

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
        try:
            await notify_user_autobuy_error(telegram_id, "при выполнении покупки", e)
        except Exception:
            pass
    finally:
        # Всегда освобождаем блокировку и сбрасываем флаг
        try:
            state['buy_in_progress'] = False
        finally:
            try:
                lock.release()
            except RuntimeError:
                pass


async def check_rise_triggers(telegram_id: int, symbol: str, bid_price: float, ask_price: float, is_rise: bool, current_time: float, user_settings: User):
    """
    Проверяет триггеры для покупок на росте цены с правильным анализом тренда.

    Логика:
    1. Триггер устанавливается на ask_price (цена продажи)
    2. Активация триггера - при пересечении ask_price уровня trigger_price (в любую сторону)
    3. Начало отсчета паузы - при активации триггера
    4. Анализ тренда во время паузы - mid цена должна только расти (без единого падения)
    5. Сброс при малейшем движении вниз mid цены → сброс триггера
    6. Ожидание нового пересечения триггера
    """
    try:
        if telegram_id not in autobuy_states:
            return

        state = autobuy_states[telegram_id]
        ask_price_float = float(ask_price)
        bid_price_float = float(bid_price)
        mid_price = (bid_price_float + ask_price_float) / 2
        pause_seconds = user_settings.pause

        # Инициализация и сохранение предыдущих цен
        prev_ask_price = state.get('last_ask_price')
        prev_mid_price = state.get('last_mid_price')
        state['last_ask_price'] = ask_price_float
        state['last_mid_price'] = mid_price

        # Проверяем, что триггер установлен
        if state.get('is_rise_trigger') and state.get('trigger_price') is not None:
            trigger_price = state['trigger_price']
            is_activated = state.get('is_trigger_activated', False)

            # ЭТАП 1: Активация триггера при пересечении уровня в любую сторону
            if not is_activated:
                if prev_ask_price is not None:
                    crossed_up = (prev_ask_price <= trigger_price < ask_price_float)
                    crossed_down = (prev_ask_price >= trigger_price > ask_price_float)
                    if crossed_up or crossed_down:
                        # Запускаем паузу и анализ тренда (используем mid цену)
                        state['is_trigger_activated'] = True
                        state['trigger_activated_time'] = current_time
                        state['pause_trend_prices'] = [mid_price]  # Сохраняем mid цену
                        state['trend_only_rise'] = True
                        state['last_pause_price'] = mid_price

                        direction = "↑" if crossed_up else "↓"
                        logger.info(
                            f"Trigger crossed {direction} for {telegram_id}: "
                            f"ask {prev_ask_price:.6f} → {ask_price_float:.6f}, "
                            f"mid {mid_price:.6f}. Starting {pause_seconds}s pause."
                        )
                        # Уведомление об активации триггера (закомментировано)
                        # from bot.config import bot_instance
                        # try:
                        #     await bot_instance.send_message(
                        #         telegram_id,
                        #         f"🔔 Триггер активирован для {symbol}\n\n"
                        #         f"📈 Цена ({ask_price_float:.6f} USDC) пересекла триггер {trigger_price:.6f} USDC\n"
                        #         f"⏱️ Начинаем анализ тренда на {pause_seconds}с"
                        #     )
                        #     logger.info(f"Trigger activation notification sent to {telegram_id}")
                        # except Exception as e:
                        #     logger.error(f"Failed to send trigger activation notification to {telegram_id}: {e}")

            # ЭТАП 2: Анализ тренда во время паузы
            else:
                triggered_time = state.get('trigger_activated_time', 0)
                pause_prices = state.get('pause_trend_prices', [])

                # 2.1 Сброс при любом движении вниз mid цены относительно prev_mid_price
                if prev_mid_price is not None and mid_price < prev_mid_price:
                    logger.info(
                        f"Mid price drop detected for {telegram_id}: {prev_mid_price:.6f} → {mid_price:.6f}. Resetting trigger."
                    )
                    reset_rise_trigger(state)
                    return

                # 2.2 Добавляем текущую mid цену в историю паузы
                pause_prices.append(mid_price)
                state['pause_trend_prices'] = pause_prices

                # 2.3 Проверяем завершение паузы
                elapsed = current_time - triggered_time
                if elapsed >= pause_seconds:
                    # Если рост без единого падения и ask цена выше триггера — покупаем
                    if state.get('trend_only_rise', True) and ask_price_float > trigger_price:
                        logger.info(
                            f"Rise conditions met for {telegram_id}: exclusive mid price rise during {pause_seconds}s pause. "
                            f"Final ask: {ask_price_float:.6f}, final mid: {mid_price:.6f}"
                        )

                        # Уведомление о покупке
                        from bot.config import bot_instance
                        try:
                            await bot_instance.send_message(
                                telegram_id,
                                f"⏫ Покупка по росту для {symbol}\n\n"
                                f"📈 Исключительный рост {pause_seconds}с\n"
                                f"🎯 Цена: {trigger_price:.6f} → {ask_price_float:.6f} USDC\n"
                                f"💰 Совершаем покупку!"
                            )
                            logger.info(f"Rise purchase notification sent to {telegram_id}")
                        except Exception as e:
                            logger.error(f"Failed to send rise purchase notification to {telegram_id}: {e}")

                        # Совершаем покупку
                        from bot.utils.autobuy_restart import FakeMessage
                        from bot.config import bot_instance
                        fake_message = FakeMessage(telegram_id, bot_instance)
                        asyncio.create_task(process_buy(telegram_id, "rise_trigger", fake_message, user_settings))

                        # Устанавливаем новый триггер по текущей цене
                        state['trigger_price'] = ask_price_float
                        state['trigger_time'] = current_time
                        state['is_trigger_activated'] = False
                        state['rise_buy_count'] += 1

                        # Очищаем данные паузы
                        state['pause_trend_prices'] = []
                        state['trend_only_rise'] = True
                        state['last_pause_price'] = None

                        logger.info(
                            f"New rise trigger set for {telegram_id} at ask price {ask_price_float:.6f}"
                        )
                    else:
                        logger.info(
                            f"Rise conditions NOT met for {telegram_id}. Final price: {ask_price_float:.6f}, "
                            f"trend_only_rise: {state.get('trend_only_rise', False)}"
                        )
                        reset_rise_trigger(state)

    except Exception as e:
        logger.error(f"Error in check_rise_triggers for {telegram_id}: {e}", exc_info=True)


def reset_rise_trigger(state):
    """Сбрасывает триггер на росте и очищает связанные данные"""
    state['is_rise_trigger'] = False
    state['trigger_price'] = None
    state['trigger_time'] = 0
    state['is_trigger_activated'] = False
    state['trigger_activated_time'] = 0
    state['pause_trend_prices'] = []
    state['trend_only_rise'] = True
    state['last_pause_price'] = None
    state['last_ask_price'] = None
    state['last_mid_price'] = None


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

            # Устанавливаем триггер для покупок на росте после КАЖДОЙ продажи
            try:
                from bot.utils.websocket_manager import websocket_manager
                bookticker_data = websocket_manager.get_current_bookticker(symbol)
                if bookticker_data:
                    ask_price = float(bookticker_data['ask_price'])  # Используем ask цену
                    current_time = time.time()
                    
                    autobuy_states[user_id]['trigger_price'] = ask_price
                    autobuy_states[user_id]['trigger_time'] = current_time
                    autobuy_states[user_id]['is_rise_trigger'] = True
                    autobuy_states[user_id]['is_trigger_activated'] = False
                    autobuy_states[user_id]['trigger_activated_time'] = 0
                    autobuy_states[user_id]['pause_trend_prices'] = []
                    autobuy_states[user_id]['trend_only_rise'] = True
                    autobuy_states[user_id]['last_pause_price'] = None
                    autobuy_states[user_id]['last_ask_price'] = None
                    autobuy_states[user_id]['last_mid_price'] = None
                    
                    logger.info(f"[AutobuyOrderUpdate] User {user_id}: Rise trigger set at ask price {ask_price:.6f} after order {order_id} filled")
                else:
                    logger.warning(f"[AutobuyOrderUpdate] User {user_id}: Could not set rise trigger - no bookTicker data")
            except Exception as e:
                logger.error(f"[AutobuyOrderUpdate] User {user_id}: Error setting rise trigger: {e}")

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
    """Периодическая проверка и очистка ресурсов + ресинк состояния из БД"""
    while telegram_id in autobuy_states:
        try:
            # Вызываем сборщик мусора
            gc.collect()

            # Журналируем статистику о количестве клиентских сессий
            client_session_count = 0
            for obj in gc.get_objects():
                if 'ClientSession' in str(type(obj)):
                    client_session_count += 1

            # Учитываем только открытые сессии; повышаем порог для предупреждения
            if client_session_count > 20:
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

            # Проверяем market connection с блокировкой для предотвращения множественных попыток
            if not websocket_manager.market_connection:
                # Проверяем, не идет ли уже процесс переподключения
                if not hasattr(websocket_manager, '_market_reconnecting'):
                    websocket_manager._market_reconnecting = True
                    try:
                        logger.warning(f"Соединение с WebSocket для рынка потеряно, переподключаемся")
                        success = await websocket_manager.connect_market_data()
                        if not success:
                            logger.error(f"Не удалось переподключиться к market WebSocket для {telegram_id}")
                            return
                    finally:
                        websocket_manager._market_reconnecting = False
                else:
                    logger.debug(f"Market WebSocket reconnection already in progress, skipping")

            # Проверяем подписку только если соединение активно
            if websocket_manager.market_connection and symbol not in websocket_manager.market_subscriptions:
                logger.warning(f"Подписка на {symbol} отсутствует, переподписываемся")
                success = await websocket_manager.subscribe_market_data([symbol])
                if not success:
                    logger.error(f"Не удалось подписаться на {symbol} для {telegram_id}")

            # ===== DB → State ресинк активных ордеров раз в ~60с =====
            # Пересобираем список активных ордеров из БД и синхронизируем in-memory состояние
            deals_qs = Deal.objects.filter(
                user=user,
                status__in=["NEW", "PARTIALLY_FILLED"],
                is_autobuy=True
            ).order_by("-created_at")

            active_deals = await sync_to_async(list)(deals_qs)

            rebuilt_active_orders = []
            for deal in active_deals:
                rebuilt_active_orders.append({
                    "order_id": deal.order_id,
                    "buy_price": float(deal.buy_price),
                    "notified": False,
                    "user_order_number": deal.user_order_number,
                })

            state = autobuy_states.get(telegram_id, {})
            current_active_orders = state.get('active_orders', [])

            # Обновляем только если реально поменялось
            if rebuilt_active_orders != current_active_orders:
                autobuy_states[telegram_id]['active_orders'] = rebuilt_active_orders
                logger.info(f"[Resync] Пересобраны active_orders для {telegram_id}: {rebuilt_active_orders}")

                # Если активных ордеров больше нет — переводим в режим ожидания новой возможности
                if not rebuilt_active_orders:
                    try:
                        pause_seconds = user.pause
                    except Exception:
                        pause_seconds = 0

                    autobuy_states[telegram_id]['last_buy_price'] = None
                    autobuy_states[telegram_id]['waiting_for_opportunity'] = True
                    autobuy_states[telegram_id]['restart_after'] = time.time() + pause_seconds if pause_seconds > 0 else 0
                    autobuy_states[telegram_id]['waiting_reported'] = False
                    logger.info(f"[Resync] Установлен режим ожидания для {telegram_id}. Пауза: {pause_seconds}s")

        except Exception as e:
            logger.error(f"Ошибка в periodic_resource_check для {telegram_id}: {e}")

        # Проверка каждые 60 секунд (ресинк и здоровье)
        await asyncio.sleep(60)
