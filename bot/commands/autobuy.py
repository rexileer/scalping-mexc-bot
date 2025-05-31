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
                    'waiting_reported': False  # Флаг для отслеживания, сообщили ли мы о том, что ожидаем
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
            
            # Проверяем, нет ли уже установленного соединения
            if symbol not in websocket_manager.market_subscriptions:
                # Подписываемся на обновления цены через WebSocket только если еще не подписаны
                await websocket_manager.connect_market_data([symbol])
                logger.info(f"Подписались на данные рынка для {symbol}")
            
            # Регистрируем колбэк для обновления цены
            async def update_price_for_autobuy(symbol_name, price_str):
                try:
                    # Проверяем, что пользователь все еще в режиме автобай
                    user_data = await sync_to_async(User.objects.filter(telegram_id=telegram_id, autobuy=True).exists)()
                    if not user_data:
                        logger.info(f"Пропускаем обработку цены - пользователь {telegram_id} больше не в режиме автобай")
                        return
                        
                    # Преобразуем цену в число
                    price = float(price_str)
                    
                    # Обновляем текущую цену
                    old_price = autobuy_states[telegram_id]['current_price']
                    autobuy_states[telegram_id]['current_price'] = price
                    
                    # Если система не готова или обрабатывает покупку - выходим
                    if not autobuy_states[telegram_id].get('is_ready', False) or buy_lock.locked():
                        return
                    
                    # Проверяем, не находимся ли мы в режиме ожидания после закрытия сделки
                    current_time = time.time()
                    restart_after = autobuy_states[telegram_id].get('restart_after', 0)
                    waiting_for_opportunity = autobuy_states[telegram_id].get('waiting_for_opportunity', False)
                    
                    if waiting_for_opportunity and restart_after > 0:
                        if current_time < restart_after:
                            # Еще не время для новой покупки - лог только один раз
                            if not autobuy_states[telegram_id].get('waiting_reported', False):
                                wait_time = restart_after - current_time
                                logger.info(f"Ожидаем возможности новой покупки для {telegram_id}. Осталось {wait_time:.1f} секунд.")
                                autobuy_states[telegram_id]['waiting_reported'] = True
                            return
                        else:
                            # Время вышло, сбрасываем таймер и разрешаем покупку
                            autobuy_states[telegram_id]['restart_after'] = 0
                            autobuy_states[telegram_id]['waiting_for_opportunity'] = False
                            autobuy_states[telegram_id]['waiting_reported'] = False
                            logger.info(f"Период ожидания после закрытия сделки истек для {telegram_id}, разрешаем новые покупки")
                            
                            # Сразу инициируем новую покупку после окончания периода ожидания
                            user_settings = await sync_to_async(User.objects.get)(telegram_id=telegram_id)
                            await message.answer(f"🔄 Возобновляем автобай после паузы. Текущая цена: {price}")
                            asyncio.create_task(process_buy(telegram_id, "after_waiting_period", message, user_settings))
                            return
                        
                    # Получаем текущие параметры
                    last_buy_price = autobuy_states[telegram_id]['last_buy_price']
                    user_settings = await sync_to_async(User.objects.get)(telegram_id=telegram_id)
                    
                    # Если нет последней покупки и не ждем возможности - это будет первая покупка
                    if not last_buy_price and not waiting_for_opportunity:
                        asyncio.create_task(process_buy(telegram_id, "initial_purchase", message, user_settings))
                        return
                    
                    # Если нет активных ордеров (все закрылись) и не ждем возможности, начинаем цикл заново
                    active_orders = autobuy_states[telegram_id]['active_orders']
                    if not active_orders and not waiting_for_opportunity and not last_buy_price:
                        asyncio.create_task(process_buy(telegram_id, "new_cycle", message, user_settings))
                        return
                    
                    # Проверяем условия для покупки, только если есть последняя цена
                    if last_buy_price:
                        loss_threshold = float(user_settings.loss)
                        profit_percent = float(user_settings.profit)
                        
                        # Проверка на падение цены
                        if ((last_buy_price - price) / last_buy_price * 100) >= loss_threshold:
                            drop_percent = (last_buy_price - price) / last_buy_price * 100
                            await message.answer(
                                f"⚠️ *Обнаружено падение цены*\n\n"
                                f"🔻 Цена снизилась на `{drop_percent:.2f}%` от покупки по `{last_buy_price:.6f}` {symbol[3:]}\n",
                                parse_mode="Markdown"
                            )
                            asyncio.create_task(process_buy(telegram_id, "price_drop", message, user_settings))
                            
                        # Проверка на рост цены
                        elif ((price - last_buy_price) / last_buy_price * 100) >= profit_percent:
                            rise_percent = (price - last_buy_price) / last_buy_price * 100
                            await message.answer(
                                f"⚠️ *Обнаружен рост цены*\n\n"
                                f"🟢 Цена выросла на `{rise_percent:.2f}%` от покупки по `{last_buy_price:.6f}` {symbol[3:]}\n",
                                parse_mode="Markdown"
                            )
                            # Добавляем паузу перед покупкой на росте согласно настройкам пользователя
                            await asyncio.sleep(user_settings.pause)
                            asyncio.create_task(process_buy(telegram_id, "price_rise", message, user_settings))
                        
                except Exception as e:
                    logger.error(f"Ошибка в обработчике цены autobuy для {telegram_id}: {e}")
            
            # Сохраняем колбэк и регистрируем его
            autobuy_states[telegram_id]['price_callbacks'].append(update_price_for_autobuy)
            await websocket_manager.register_price_callback(symbol, update_price_for_autobuy)
            
            # Получаем текущую цену через REST API для начала
            ticker_data = trade_client.ticker_price(symbol)
            handle_mexc_response(ticker_data, "Получение цены")
            current_price = float(ticker_data["price"])
            autobuy_states[telegram_id]['current_price'] = current_price
            
            # Отмечаем, что система готова обрабатывать обновления
            autobuy_states[telegram_id]['is_ready'] = True
            
            # Если нет активных ордеров и есть начальная цена, делаем первую покупку
            if not active_orders and current_price > 0:
                await process_buy(telegram_id, "initial_purchase", message, user)
            
            # Планируем задачу проверки ресурсов
            asyncio.create_task(periodic_resource_check(telegram_id))
            
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
                        await message.answer(f"🔄 Возобновляем автобай после паузы (основной цикл). Текущая цена: {autobuy_states[telegram_id]['current_price']}")
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
    
    # Используем Lock для предотвращения множественных покупок одновременно
    lock = asyncio.Lock()
    
    # Проверяем, не слишком ли быстро выполняем покупку (защита от множественных вызовов)
    current_time = time.time()
    last_trade_time = autobuy_states[telegram_id].get('last_trade_time', 0)
    TRADE_COOLDOWN = 15  # Минимальный интервал между операциями в секундах
    
    if current_time - last_trade_time < TRADE_COOLDOWN:
        logger.info(f"Пропускаем покупку - слишком быстро после последней ({current_time - last_trade_time}с < {TRADE_COOLDOWN}с)")
        return
    
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
        autobuy_states[telegram_id]['last_trade_time'] = current_time
        
        # Сбрасываем флаги ожидания
        autobuy_states[telegram_id]['waiting_for_opportunity'] = False
        autobuy_states[telegram_id]['restart_after'] = 0
        autobuy_states[telegram_id]['waiting_reported'] = False
        
        # Получаем текущие данные
        client_session = None
        try:
            trade_client = Trade(api_key=user.api_key, api_secret=user.api_secret)
            symbol = user.pair.replace("/", "")
            buy_amount = float(user.buy_amount)
            profit_percent = float(user.profit)
            
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
                return

            spent = float(order_info["cummulativeQuoteQty"])
            if spent == 0:
                await message.answer("❗ Ошибка при создании ордера (spent=0).")
                return
            
            real_price = spent / executed_qty if executed_qty > 0 else 0
            
            # Сохраняем новую цену последней покупки сразу
            autobuy_states[telegram_id]['last_buy_price'] = real_price
            
            # Логируем причину покупки
            logger.info(f"Buy triggered for {telegram_id} because of {reason}. New last_buy_price: {real_price}")
            
            # Расчёт цены продажи
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

            await message.answer(
                f"🟢 *СДЕЛКА {user_order_number} ОТКРЫТА*\n\n"
                f"📉 Куплено по: `{real_price:.6f}` {symbol[3:]}\n"
                f"📦 Кол-во: `{executed_qty:.6f}` {symbol[:3]}\n"
                f"💸 Потрачено: `{spent:.2f}` {symbol[3:]}\n\n"
                f"📈 Лимит на продажу: `{sell_price:.6f}` {symbol[3:]}\n",
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.error(f"Ошибка в процессе выполнения покупки для {telegram_id}: {e}")
            error_message = parse_mexc_error(e)
            await message.answer(f"❌ Ошибка при покупке: {error_message}")
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
        return
    
    # Отладочный лог с полным состоянием
    logger.info(f"Processing order update for user {user_id}: order_id={order_id}, status={status}, current_price={autobuy_states[user_id].get('current_price')}, last_buy_price={autobuy_states[user_id].get('last_buy_price')}")
    
    active_orders = autobuy_states[user_id]['active_orders']
    old_last_buy_price = autobuy_states[user_id].get('last_buy_price')
    
    # Ищем ордер среди активных
    order_index = next((i for i, order in enumerate(active_orders) if order["order_id"] == order_id), None)
    
    if order_index is not None:
        if status in ["FILLED", "CANCELED"]:
            # Получаем информацию о завершенном ордере
            order_info = active_orders[order_index]
            
            # Если ордер исполнен или отменен, удаляем его из активных
            active_orders.pop(order_index)
            autobuy_states[user_id]['active_orders'] = active_orders
            
            # Если не осталось активных ордеров, устанавливаем паузу перед следующей покупкой
            if not active_orders:
                # Получаем пользовательские настройки для определения паузы
                try:
                    user = await sync_to_async(User.objects.get)(telegram_id=user_id)
                    pause_seconds = user.pause
                    
                    # Устанавливаем время следующей возможной покупки
                    autobuy_states[user_id]['last_buy_price'] = None
                    autobuy_states[user_id]['waiting_for_opportunity'] = True
                    autobuy_states[user_id]['restart_after'] = time.time() + pause_seconds
                    autobuy_states[user_id]['waiting_reported'] = False
                    
                    logger.info(f"Reset last_buy_price to None as no active orders remain for user {user_id}. Next buy possible after {pause_seconds} seconds")
                except Exception as e:
                    logger.error(f"Ошибка при установке паузы после закрытия ордера: {e}")
                    # Если не удалось получить настройки паузы, просто сбрасываем last_buy_price
                    autobuy_states[user_id]['last_buy_price'] = None
                    logger.info(f"Reset last_buy_price to None as no active orders remain for user {user_id}")
            else:
                # Иначе устанавливаем last_buy_price по самому свежему ордеру
                most_recent_order = max(active_orders, key=lambda x: x.get("user_order_number", 0))
                autobuy_states[user_id]['last_buy_price'] = most_recent_order["buy_price"]
                logger.info(f"Updated last_buy_price to {most_recent_order['buy_price']} for user {user_id} from order #{most_recent_order['user_order_number']}")

    # Лог изменений
    if old_last_buy_price != autobuy_states[user_id].get('last_buy_price'):
        logger.info(f"last_buy_price changed for user {user_id}: {old_last_buy_price} -> {autobuy_states[user_id].get('last_buy_price')}")


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
            
        except Exception as e:
            logger.error(f"Ошибка в periodic_resource_check для {telegram_id}: {e}")
        
        # Проверка каждые 30 секунд
        await asyncio.sleep(30)
