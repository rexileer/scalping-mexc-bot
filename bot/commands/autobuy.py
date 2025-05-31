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

# Словарь для хранения состояния autobuy для каждого пользователя
autobuy_states = {}  # {user_id: {'last_buy_price': float, 'active_orders': []}}

async def autobuy_loop(message: Message, telegram_id: int):
    startup_fail_count = 0

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
                    'price_callbacks': []
                }
            
            # Подписываемся на обновления цены через WebSocket
            await websocket_manager.connect_market_data([symbol])
            
            # Регистрируем колбэк для обновления цены
            async def update_price_for_autobuy(symbol_name, price_str):
                price = float(price_str)
                autobuy_states[telegram_id]['current_price'] = price
                logger.debug(f"Обновление цены для autobuy {telegram_id}: {symbol_name} - {price}")
            
            autobuy_states[telegram_id]['price_callbacks'].append(update_price_for_autobuy)
            await websocket_manager.register_price_callback(symbol, update_price_for_autobuy)
            
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

            # Получаем текущую цену через REST API для начала
            ticker_data = trade_client.ticker_price(symbol)
            handle_mexc_response(ticker_data, "Получение цены")
            current_price = float(ticker_data["price"])
            autobuy_states[telegram_id]['current_price'] = current_price

            # Основной цикл автобая
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
                    
                    # Обновляем пользователя и его настройки
                    user = await sync_to_async(User.objects.get)(telegram_id=telegram_id)
                    buy_amount = float(user.buy_amount)
                    profit_percent = float(user.profit)
                    loss_threshold = float(user.loss)
                    
                    # Получаем текущую цену из состояния (обновляется через WebSocket)
                    current_price = autobuy_states[telegram_id]['current_price']
                    last_buy_price = autobuy_states[telegram_id]['last_buy_price']
                    active_orders = autobuy_states[telegram_id]['active_orders']

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
                            continue

                        spent = float(order_info["cummulativeQuoteQty"])
                        if spent == 0:
                            await message.answer("❗ Ошибка при создании ордера (spent=0).")
                            continue
                        
                        real_price = spent / executed_qty if executed_qty > 0 else 0
                        
                        # Обновляем last_buy_price в состоянии
                        autobuy_states[telegram_id]['last_buy_price'] = real_price
                        
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

                    # Проверяем активные ордера через WebSocket
                    # Нам не нужно делать периодические запросы, так как обновления придут автоматически
                    
                    # Интервалы между проверками логики
                    await asyncio.sleep(2 if active_orders else user.pause)

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
                        
                        # Удаляем колбэки и состояние
                        if telegram_id in autobuy_states:
                            # Импортируем websocket_manager внутри блока
                            from bot.utils.websocket_manager import websocket_manager
                            
                            for callback in autobuy_states[telegram_id]['price_callbacks']:
                                symbol_to_unregister = user.pair.replace("/", "")
                                if symbol_to_unregister in websocket_manager.price_callbacks:
                                    if callback in websocket_manager.price_callbacks[symbol_to_unregister]:
                                        websocket_manager.price_callbacks[symbol_to_unregister].remove(callback)
                            del autobuy_states[telegram_id]
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
            
            # Удаляем колбэки и состояние
            if telegram_id in autobuy_states:
                # Импортируем websocket_manager внутри блока
                from bot.utils.websocket_manager import websocket_manager
                
                for callback in autobuy_states[telegram_id]['price_callbacks']:
                    symbol_to_unregister = user.pair.replace("/", "")
                    if symbol_to_unregister in websocket_manager.price_callbacks:
                        if callback in websocket_manager.price_callbacks[symbol_to_unregister]:
                            websocket_manager.price_callbacks[symbol_to_unregister].remove(callback)
                del autobuy_states[telegram_id]
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


# Добавим функцию для обработки обновлений ордеров autobuy через WebSocket
async def process_order_update_for_autobuy(order_id, symbol, status, user_id):
    """Обработка обновлений ордеров для автобая через WebSocket"""
    if user_id not in autobuy_states:
        return
    
    active_orders = autobuy_states[user_id]['active_orders']
    
    # Ищем ордер среди активных
    order_index = next((i for i, order in enumerate(active_orders) if order["order_id"] == order_id), None)
    
    if order_index is not None:
        if status in ["FILLED", "CANCELED"]:
            # Получаем информацию о завершенном ордере
            order_info = active_orders[order_index]
            
            # Если ордер исполнен или отменен, удаляем его из активных
            active_orders.pop(order_index)
            autobuy_states[user_id]['active_orders'] = active_orders
            
            # Если нет больше активных ордеров, сбрасываем last_buy_price
            if not active_orders:
                autobuy_states[user_id]['last_buy_price'] = None
                logger.info(f"Reset last_buy_price to None as no active orders remain for user {user_id}")
            else:
                # Иначе устанавливаем last_buy_price по самому свежему ордеру
                most_recent_order = max(active_orders, key=lambda x: x.get("user_order_number", 0))
                autobuy_states[user_id]['last_buy_price'] = most_recent_order["buy_price"]
                logger.info(f"Updated last_buy_price to {most_recent_order['buy_price']} for user {user_id} from order #{most_recent_order['user_order_number']}")
