from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
import asyncio
# from bot.commands.buy import monitor_order
from bot.commands.autobuy import autobuy_loop
from bot.utils.mexc import get_user_client
from bot.utils.websocket_manager import websocket_manager
from bot.utils.user_autobuy_tasks import user_autobuy_tasks
from users.models import User, Deal
from logger import logger
from bot.keyboards.inline import get_period_keyboard, get_pagination_keyboard
from asgiref.sync import sync_to_async
from mexc_sdk import Trade  # Предполагаем, что именно этот класс отвечает за торговые операции
from django.utils.timezone import localtime
from bot.utils.mexc import handle_mexc_response, get_actual_order_status
from bot.utils.api_errors import parse_mexc_error
from bot.utils.bot_logging import log_command
import math

router = Router()

# /price
@router.message(Command("price"))
async def get_user_price(message: Message):
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name or str(user_id)
    command = "/price"
    response_text = ""
    success = True

    try:
        # Получаем клиента и пару для пользователя
        client, pair = get_user_client(message.from_user.id)

        # Проверяем, что валидная пара получена
        if not pair:
            raise ValueError("Валютная пара не указана.")

        # Сначала получаем текущую цену с помощью REST API
        ticker = await asyncio.to_thread(client.ticker_price, pair)
        current_price = ticker['price']

        # Формируем начальный ответ
        response_text = f"Цена {pair}: {current_price}"
        sent_message = await message.answer(response_text)

        # Создаём или подключаемся к WebSocket для рыночных данных
        if not websocket_manager.market_connection:
            await websocket_manager.connect_market_data([pair])
        elif pair not in websocket_manager.market_subscriptions:
            await websocket_manager.subscribe_market_data([pair])

        # Функция для обновления цены в сообщении
        async def update_price_message(symbol, price):
            nonlocal sent_message
            await sent_message.edit_text(f"Цена {symbol}: {price} (обновлено)")

        # Регистрируем callback для обновления цены в реальном времени
        await websocket_manager.register_price_callback(pair, update_price_message)

        # Через 10 секунд удалим callback (чтобы не накапливать их)
        await asyncio.sleep(10)

        if pair in websocket_manager.price_callbacks:
            if update_price_message in websocket_manager.price_callbacks[pair]:
                websocket_manager.price_callbacks[pair].remove(update_price_message)

    except ValueError as e:
        # Обрабатываем ошибки, если ошибка в API или данных
        response_text = f"Ошибка: {e}"
        success = False
        await message.answer(response_text)
    except Exception as e:
        # Логируем и отправляем пользователю общую ошибку
        logger.error(f"Произошла ошибка при получении цены: {e}")
        response_text = "Произошла ошибка при получении цены."
        success = False
        await message.answer(response_text)

    # Логируем команду и ответ
    await log_command(
        user_id=user_id,
        command=command,
        response=response_text,
        success=success,
        extra_data={
            "username": username,
            "chat_id": message.chat.id,
            "pair": pair if 'pair' in locals() else None
        }
    )


@router.message(Command("balance"))
async def balance_handler(message: Message):
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name or str(user_id)
    command = "/balance"
    response_text = ""
    success = True
    extra_data = {"username": username, "chat_id": message.chat.id}

    try:
        user = User.objects.get(telegram_id=message.from_user.id)
        client, pair = get_user_client(message.from_user.id)
        extra_data["pair"] = pair

        account_info = await asyncio.to_thread(client.account_info)
        logger.info(f"Account Info for {message.from_user.id}: {account_info}")

        # Определим интересующие нас токены на основе пары
        base_asset = pair[:-4]  # например, KAS или BTC
        quote_asset = pair[-4:]  # например, USDT или USDC
        relevant_assets = {base_asset, quote_asset}

        balances_message = "💰 <b>БАЛАНС</b>\n"

        for balance in account_info['balances']:
            asset = balance['asset']
            if asset not in relevant_assets:
                continue

            free = float(balance['free'])
            locked = float(balance['locked'])

            balances_message += (
                f"\n<b>{asset}</b>\n"
                f"Доступно: {format(free, ',.6f').replace(',', 'X').replace('.', ',').replace('X', '.').replace(' ', ' ')}\n"
                f"Заморожено: {format(locked, ',.6f').replace(',', 'X').replace('.', ',').replace('X', '.').replace(' ', ' ')}"
            )

        orders = await asyncio.to_thread(client.open_orders, symbol=pair)
        logger.info(f"Open Orders for {message.from_user.id}: {orders}")
        open_orders_count = len(orders)
        extra_data["open_orders_count"] = open_orders_count

        total_order_amount = sum([float(order['origQty']) for order in orders])
        total_order_value = sum([float(order['price']) * float(order['origQty']) for order in orders])
        avg_price = total_order_value / total_order_amount if total_order_amount > 0 else 0

        orders_message = (
            f"\n\n📄 <b>Ордера</b>\n"
            f"Количество: {open_orders_count}\n"
            f"Сумма исполнения: {format(total_order_value, ',.4f').replace(',', 'X').replace('.', ',').replace('X', '.')} {quote_asset}\n"
            f"Средняя цена исполнения: {format(avg_price, ',.6f').replace(',', 'X').replace('.', ',').replace('X', '.')} {quote_asset}"
        )

        response_text = balances_message + orders_message
        await message.answer(response_text, parse_mode="HTML")
        logger.info(f"User {user.telegram_id} requested balance and orders.")

    except Exception as e:
        logger.error(f"Ошибка при получении баланса для пользователя {message.from_user.id}: {e}")
        response_text = "Произошла ошибка при получении баланса."
        success = False
        await message.answer(response_text)

    # Логируем команду и ответ
    await log_command(
        user_id=user_id,
        command=command,
        response=response_text,
        success=success,
        extra_data=extra_data
    )


# /buy
@router.message(Command("buy"))
async def buy_handler(message: Message):
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name or str(user_id)
    command = "/buy"
    response_text = ""
    success = True
    extra_data = {"username": username, "chat_id": message.chat.id}

    try:
        user = User.objects.get(telegram_id=message.from_user.id)

        if not user.pair:
            response_text = "❗ Вы не выбрали торговую пару. Введите /pair для выбора."
            success = False
            await message.answer(response_text)
            return

        symbol = user.pair.replace("/", "")
        extra_data["symbol"] = symbol
        trade_client = Trade(api_key=user.api_key, api_secret=user.api_secret)
        buy_amount = float(user.buy_amount)
        extra_data["buy_amount"] = buy_amount

        # 1. Создаём ордер
        buy_order = await asyncio.to_thread(
            trade_client.new_order,
            symbol,
            "BUY",
            "MARKET",
            {"quoteOrderQty": buy_amount},
        )
        handle_mexc_response(buy_order, "Покупка через /buy")

        order_id = buy_order["orderId"]
        extra_data["buy_order_id"] = order_id

        # 2. Подтягиваем детали через query_order
        order_info = await asyncio.to_thread(trade_client.query_order, symbol, {"orderId": order_id})
        logger.info(f"Детали ордера {order_id}: {order_info}")

        # 3. Получаем количество и среднюю цену
        executed_qty = float(order_info.get("executedQty", 0))
        if executed_qty == 0:
            response_text = "❗ Ошибка при создании ордера (executedQty=0)."
            success = False
            await message.answer(response_text)
            return

        spent = float(order_info["cummulativeQuoteQty"])
        if spent == 0:
            response_text = "❗ Ошибка при создании ордера (spent=0)."
            success = False
            await message.answer(response_text)
            return

        real_price = spent / executed_qty if executed_qty > 0 else 0
        extra_data["real_price"] = real_price
        extra_data["executed_qty"] = executed_qty
        extra_data["spent"] = spent

        # 4. Считаем цену продажи
        profit_percent = float(user.profit)
        sell_price = round(real_price * (1 + profit_percent / 100), 6)
        extra_data["sell_price"] = sell_price
        extra_data["profit_percent"] = profit_percent

        # 5. Выставляем лимитный SELL ордер
        sell_order = await asyncio.to_thread(
            trade_client.new_order,
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
        extra_data["sell_order_id"] = sell_order_id
        logger.info(f"SELL ордер {sell_order_id} выставлен на {sell_price:.6f} {symbol[3:]}")

        # 6. Сохраняем ордер в базу
        # Получаем следующий номер
        last_number = await sync_to_async(
            lambda: Deal.objects.filter(user=user).count()
        )()
        user_order_number = last_number + 1
        extra_data["user_order_number"] = user_order_number
        deal = await sync_to_async(Deal.objects.create)(
            user=user,
            order_id=sell_order_id,
            user_order_number=user_order_number,
            symbol=symbol,
            buy_price=real_price,
            quantity=executed_qty,
            sell_price=sell_price,
            status="NEW"
        )

        # 6.1 Уточняем начальный статус через REST сразу после создания SELL
        try:
            order_check = await asyncio.to_thread(trade_client.query_order, symbol, {"orderId": sell_order_id})
            current_status = order_check.get("status")
            if current_status and current_status != deal.status:
                deal.status = current_status
                await sync_to_async(deal.save)()
        except Exception as e:
            logger.warning(f"Не удалось уточнить начальный статус ордера {sell_order_id}: {e}")

        # 7. Отправляем ответ
        response_text = (
            f"🟢 *СДЕЛКА {user_order_number} ОТКРЫТА*\n\n"
            f"📉 Куплено по: `{real_price:.6f}` {symbol[3:]}\n"
            f"📦 Кол-во: `{executed_qty:.6f}` {symbol[:3]}\n"
            f"💸 Потрачено: `{spent:.2f}` {symbol[3:]}\n\n"
            f"📈 Лимит на продажу: `{sell_price:.6f}` {symbol[3:]}"
        )
        await message.answer(response_text, parse_mode="Markdown")

        logger.info(f"BUY + SELL for {user.telegram_id}: {executed_qty} {symbol} @ {real_price} -> {sell_price}")

        # 8. Не запускаем мониторинг - WebSocket будет отслеживать изменения
        # Статус будет обновляться автоматически через WebSocket

    except Exception as e:
        logger.exception("Ошибка при выполнении /buy")
        response_text = f"❌ {parse_mexc_error(e)}"
        success = False
        await message.answer(response_text)

    # Логируем команду и ответ
    await log_command(
        user_id=user_id,
        command=command,
        response=response_text,
        success=success,
        extra_data=extra_data
    )


# /auto_buy
@router.message(Command("autobuy"))
async def autobuy_handler(message: Message):
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name or str(user_id)
    command = "/autobuy"
    response_text = ""
    success = True
    extra_data = {"username": username, "chat_id": message.chat.id}

    try:
        telegram_id = message.from_user.id
        user = await sync_to_async(User.objects.get)(telegram_id=telegram_id)
        extra_data["pair"] = user.pair

        if user.autobuy:
            response_text = "⚠️ Автобай уже запущен. Остановить: /stop"
            await message.answer(response_text)
            return

        user.autobuy = True
        await sync_to_async(user.save)()


        # В конце успешного выполнения:
        response_text = "🟢 Автобай запущен"
        await message.answer(response_text)

        # Далее запуск задачи
        task = asyncio.create_task(autobuy_loop(message, telegram_id))
        user_autobuy_tasks[telegram_id] = task

    except Exception as e:
        logger.exception(f"Ошибка при запуске автобая для {user_id}")
        response_text = f"❌ Ошибка при запуске автобая: {str(e)}"
        success = False
        await message.answer(response_text)

    # Логируем команду и ответ
    await log_command(
        user_id=user_id,
        command=command,
        response=response_text,
        success=success,
        extra_data=extra_data
    )

# /stop
@router.message(Command("stop"))
async def stop_autobuy(message: Message):
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name or str(user_id)
    command = "/stop"
    response_text = ""
    success = True
    extra_data = {"username": username, "chat_id": message.chat.id}

    try:
        telegram_id = message.from_user.id

        # Если есть задача для пользователя, отменяем её
        if telegram_id in user_autobuy_tasks and not user_autobuy_tasks[telegram_id].done():
            user_autobuy_tasks[telegram_id].cancel()
            logger.info(f"Autobuy task for user {telegram_id} cancelled")

        # Меняем статус в базе
        user = await sync_to_async(User.objects.get)(telegram_id=telegram_id)
        user.autobuy = False
        await sync_to_async(user.save)()

        response_text = "🔴 Автобай остановлен"
        await message.answer(response_text)

    except Exception as e:
        logger.exception(f"Ошибка при остановке автобая для {user_id}")
        response_text = f"❌ Ошибка при остановке автобая: {str(e)}"
        success = False
        await message.answer(response_text)

    # Логируем команду и ответ
    await log_command(
        user_id=user_id,
        command=command,
        response=response_text,
        success=success,
        extra_data=extra_data
    )

# /status
@router.message(Command("status"))
async def status_handler(message: Message):
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name or str(user_id)
    command = "/status"
    response_text = ""
    success = True
    extra_data = {"username": username, "chat_id": message.chat.id}

    try:
        # Показываем первую страницу при вызове команды
        await show_status_page(message, user_id, page=1)

    except Exception as e:
        logger.error(f"Ошибка при получении статуса для пользователя {user_id}: {e}")
        response_text = "❌ Ошибка при получении статуса."
        success = False
        await message.answer(response_text)
        extra_data["error"] = str(e)

    # Логируем команду и ответ
    await log_command(
        user_id=user_id,
        command=command,
        response="Запрошен статус ордеров",
        success=success,
        extra_data=extra_data
    )

# Обработчик пагинации для функции status
@router.callback_query(F.data.startswith("status_page:"))
async def status_pagination_handler(callback: CallbackQuery):
    # Получаем данные из callback_data
    parts = callback.data.split(":")
    if len(parts) != 3 or parts[0] != "status_page":
        await callback.answer("Неверный формат данных")
        return

    try:
        user_id = int(parts[1])
        page = int(parts[2])

        # Проверяем, что пользователь нажал свою кнопку
        if user_id != callback.from_user.id:
            await callback.answer("Это не ваша кнопка")
            return

        logger.info(f"Переход на страницу {page} для пользователя {user_id}")

        # Получаем данные для отображения
        user = await sync_to_async(User.objects.get)(telegram_id=user_id)

        header = "🔁 <b>Автобай запущен.</b>" if user.autobuy else "⚠️ <b>Автобай не запущен.</b>"

        # Получаем активные ордера из базы (без обновления статусов)
        active_deals = await sync_to_async(list)(Deal.objects.filter(
            user=user,
            status__in=["PARTIALLY_FILLED", "NEW"]
        ).order_by("-created_at"))

        # Расчет параметров пагинации
        orders_per_page = 10  # Максимальное количество ордеров на странице
        total_orders = len(active_deals)
        total_pages = math.ceil(total_orders / orders_per_page) if total_orders > 0 else 1

        # Валидация страницы
        if page < 1:
            page = 1
        elif page > total_pages:
            page = total_pages

        # Определяем, какие ордера показывать на текущей странице
        start_idx = (page - 1) * orders_per_page
        end_idx = start_idx + orders_per_page
        current_page_deals = active_deals[start_idx:end_idx]

        # Подготовка сообщения
        current_chunk = header

        if current_page_deals:
            for deal in reversed(current_page_deals):  # От старых к новым
                try:
                    date_str = localtime(deal.created_at).strftime("%d %B %Y %H:%M:%S")
                    autobuy_note = " (AutoBuy)" if deal.is_autobuy else ""
                    symbol = deal.symbol

                    formatted = (
                        f"\n\n<u>{deal.user_order_number}. Ордер на продажу{autobuy_note}</u>\n\n"
                        f"<b>{deal.quantity:.6f} {symbol[:3]}</b>\n"
                        f"- Куплено по <b>{deal.buy_price:.6f}</b> (<b>{deal.buy_price * deal.quantity:.2f}</b> {symbol[3:]})\n"
                        f"- Продается по <b>{deal.sell_price:.6f}</b> (<b>{deal.sell_price * deal.quantity:.2f}</b> {symbol[3:]})\n\n"
                        f"<i>{date_str}</i>"
                    )

                    current_chunk += formatted
                except Exception as e:
                    logger.error(f"Ошибка при обработке сделки {deal.user_order_number}: {e}")
                    continue
        else:
            current_chunk += "\n\nУ вас нет активных ордеров."

        # Добавляем информацию о времени обновления
        current_chunk += f"\n\n<i>Обновлено: {localtime().strftime('%H:%M:%S')}</i>"

        # Добавляем клавиатуру пагинации если больше чем orders_per_page ордеров
        keyboard = None
        if total_orders > orders_per_page:
            keyboard = get_pagination_keyboard(page, total_pages, user_id)

        # Редактируем сообщение напрямую
        try:
            await callback.message.edit_text(
                text=current_chunk,
                parse_mode="HTML",
                reply_markup=keyboard
            )
            logger.info(f"Успешно отредактировано сообщение для пользователя {user_id}, страница {page}")
        except Exception as e:
            logger.error(f"Ошибка при редактировании через callback: {e}", exc_info=True)
            # Если не удалось отредактировать, отправляем новое сообщение
            await callback.message.answer(
                text=current_chunk,
                parse_mode="HTML",
                reply_markup=keyboard
            )

        # Отвечаем на callback, чтобы убрать часы загрузки
        await callback.answer()

    except Exception as e:
        logger.error(f"Ошибка при обработке пагинации: {e}", exc_info=True)
        await callback.answer("Произошла ошибка")

# Функция для отображения страницы статуса ордеров
async def show_status_page(message, user_id, page=1, check_status=True):
    try:
        # Получаем информацию о пользователе
        user = await sync_to_async(User.objects.get)(telegram_id=user_id)

        header = "🔁 <b>Автобай запущен.</b>" if user.autobuy else "⚠️ <b>Автобай не запущен.</b>"

        # Ордера для отображения
        active_deals = []

        # Если запрошено обновление статусов - получаем данные из API
        if check_status:
            try:
                # Получаем клиента для пользователя
                client = None
                symbol = None
                try:
                    client, pair = get_user_client(user_id)
                    symbol = pair  # Используем пару из настроек пользователя
                except Exception as e:
                    logger.error(f"Ошибка при получении клиента: {e}")

                # Если клиент получен успешно, запрашиваем все открытые ордера пользователя
                if client and symbol:
                    # Получаем все ордера пользователя из базы
                    user_deals = await sync_to_async(list)(Deal.objects.filter(user=user))

                    # Создаем словарь для быстрого поиска ордеров по ID
                    deals_by_id = {deal.order_id: deal for deal in user_deals}

                    # Получаем все открытые ордера для пары из API
                    try:
                        open_orders = client.open_orders(symbol=symbol)
                        logger.info(f"Получено {len(open_orders)} открытых ордеров для пользователя {user_id}")

                        # Создаем множество ID ордеров из API для быстрой проверки
                        api_order_ids = {str(order['orderId']) for order in open_orders}

                        # Ищем ордера, которые были NEW в базе, но не найдены в API
                        for deal_id, deal in deals_by_id.items():
                            if deal.status in ["NEW", "PARTIALLY_FILLED"] and deal_id not in api_order_ids:
                                # Проверяем статус через API для подтверждения
                                api_status = await sync_to_async(get_actual_order_status)(
                                    user, deal.symbol, deal.order_id
                                )

                                # Если ордер не найден или завершен, отмечаем как SKIPPED
                                if api_status == "ERROR" or api_status not in ["NEW", "PARTIALLY_FILLED"]:
                                    deal.status = "SKIPPED"
                                    await sync_to_async(deal.save)()
                                    logger.info(f"Ордер {deal_id} помечен как SKIPPED (не найден в API)")
                                else:
                                    # Обновляем статус из API
                                    deal.status = api_status
                                    await sync_to_async(deal.save)()

                        # Обновляем статусы в базе и формируем список активных ордеров
                        for order in open_orders:
                            order_id = str(order['orderId'])
                            current_status = order['status']

                            # Проверяем, есть ли ордер в нашей базе
                            if order_id in deals_by_id:
                                deal = deals_by_id[order_id]
                                # Если статус изменился, обновляем его
                                if deal.status != current_status:
                                    deal.status = current_status
                                    await sync_to_async(deal.save)()

                                # Добавляем в список активных, если статус соответствует
                                if current_status in ["PARTIALLY_FILLED", "NEW"]:
                                    active_deals.append(deal)
                            else:
                                # Этот ордер не в нашей базе, возможно это ордер созданный в другом месте
                                logger.info(f"Найден ордер {order_id}, которого нет в базе данных")

                    except Exception as e:
                        logger.error(f"Ошибка при получении открытых ордеров: {e}")

                # После всех проверок через API получаем активные ордера из базы
                active_deals = await sync_to_async(list)(Deal.objects.filter(
                    user=user,
                    status__in=["PARTIALLY_FILLED", "NEW"]
                ).order_by("-created_at"))

            except Exception as e:
                logger.error(f"Ошибка при обновлении статусов: {e}")
                # Продолжаем с данными из базы
                active_deals = await sync_to_async(list)(Deal.objects.filter(
                    user=user,
                    status__in=["PARTIALLY_FILLED", "NEW"]
                ).order_by("-created_at"))
        else:
            # Если не обновляем статусы, просто получаем активные ордера из базы
            active_deals = await sync_to_async(list)(Deal.objects.filter(
                user=user,
                status__in=["PARTIALLY_FILLED", "NEW"]
            ).order_by("-created_at"))

        # Расчет параметров пагинации
        orders_per_page = 10  # Максимальное количество ордеров на странице
        total_orders = len(active_deals)
        total_pages = math.ceil(total_orders / orders_per_page) if total_orders > 0 else 1

        # Валидация страницы
        if page < 1:
            page = 1
        elif page > total_pages:
            page = total_pages

        # Определяем, какие ордера показывать на текущей странице
        start_idx = (page - 1) * orders_per_page
        end_idx = start_idx + orders_per_page
        current_page_deals = active_deals[start_idx:end_idx]

        # Подготовка сообщения
        current_chunk = header

        if current_page_deals:
            for deal in reversed(current_page_deals):  # От старых к новым
                try:
                    date_str = localtime(deal.created_at).strftime("%d %B %Y %H:%M:%S")
                    autobuy_note = " (AutoBuy)" if deal.is_autobuy else ""
                    symbol = deal.symbol

                    formatted = (
                        f"\n\n<u>{deal.user_order_number}. Ордер на продажу{autobuy_note}</u>\n\n"
                        f"<b>{deal.quantity:.6f} {symbol[:3]}</b>\n"
                        f"- Куплено по <b>{deal.buy_price:.6f}</b> (<b>{deal.buy_price * deal.quantity:.2f}</b> {symbol[3:]})\n"
                        f"- Продается по <b>{deal.sell_price:.6f}</b> (<b>{deal.sell_price * deal.quantity:.2f}</b> {symbol[3:]})\n\n"
                        f"<i>{date_str}</i>"
                    )

                    current_chunk += formatted
                except Exception as e:
                    logger.error(f"Ошибка при обработке сделки {deal.user_order_number}: {e}")
                    continue
        else:
            current_chunk += "\n\nУ вас нет активных ордеров."

        # Добавляем информацию о времени обновления
        current_chunk += f"\n\n<i>Обновлено: {localtime().strftime('%H:%M:%S')}</i>"

        # Добавляем клавиатуру пагинации если больше чем orders_per_page ордеров
        keyboard = None
        if total_orders > orders_per_page:
            keyboard = get_pagination_keyboard(page, total_pages, user_id)

        # Проверяем тип сообщения и соответственно отправляем или редактируем
        if isinstance(message, Message):
            # Если это команда /status, отправляем новое сообщение
            sent_message = await message.answer(current_chunk, parse_mode="HTML",
                                              reply_markup=keyboard)
            return sent_message
        else:
            # Если это редактирование после нажатия на кнопку, редактируем существующее
            try:
                logger.info(f"Редактирование сообщения для пользователя {user_id}, страница {page}")
                await message.edit_text(current_chunk, parse_mode="HTML",
                                       reply_markup=keyboard)
                return message
            except Exception as e:
                logger.error(f"Ошибка при редактировании сообщения: {e}, тип: {type(e)}", exc_info=True)
                # В случае ошибки редактирования пробуем отправить новое сообщение
                # Используем message.answer вместо message.chat.send_message
                try:
                    sent_message = await message.answer(current_chunk, parse_mode="HTML",
                                              reply_markup=keyboard)
                    logger.info("Отправлено новое сообщение вместо редактирования")
                    return sent_message
                except Exception as new_e:
                    logger.error(f"Не удалось отправить новое сообщение: {new_e}")
                    return None

    except Exception as e:
        logger.error(f"Ошибка при отображении страницы статуса: {e}", exc_info=True)
        error_message = "❌ Ошибка при получении статуса."

        if isinstance(message, Message):
            await message.answer(error_message)
        else:
            try:
                # В случае ошибки при редактировании отправляем новое сообщение
                await message.answer(error_message)
            except:
                # Если не удалось использовать message.answer, используем chat.send_message
                await message.chat.send_message(error_message)


# /stats
@router.message(Command("stats"))
async def ask_stats_period(message: Message):
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name or str(user_id)
    command = "/stats"
    response_text = "Выберите период для статистики:"
    success = True
    extra_data = {"username": username, "chat_id": message.chat.id}

    try:
        # Отправляем клавиатуру с выбором периода
        keyboard = get_period_keyboard()
        await message.answer(response_text, reply_markup=keyboard)

    except Exception as e:
        logger.exception(f"Ошибка при запросе периода статистики для {user_id}")
        response_text = f"❌ Ошибка при получении статистики: {str(e)}"
        success = False
        await message.answer(response_text)

    # Логируем команду и ответ
    await log_command(
        user_id=user_id,
        command=command,
        response=response_text,
        success=success,
        extra_data=extra_data
    )

# Обработчик для неактивных кнопок
@router.callback_query(F.data == "dummy_callback")
async def dummy_callback_handler(callback: CallbackQuery):
    await callback.answer("Действие недоступно")
