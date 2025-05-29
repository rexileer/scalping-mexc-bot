from aiogram import Router, F
from aiogram.types import Message
from aiogram.filters import Command
import asyncio
from bot.commands.buy import monitor_order
from bot.commands.autobuy import autobuy_loop
from bot.utils.mexc import get_user_client
from bot.utils.user_autobuy_tasks import user_autobuy_tasks
from users.models import User, Deal
from logger import logger
from bot.keyboards.inline import get_period_keyboard
from asgiref.sync import sync_to_async
from mexc_sdk import Trade  # Предполагаем, что именно этот класс отвечает за торговые операции
from django.utils.timezone import localtime
from bot.utils.mexc import handle_mexc_response, get_actual_order_status
from bot.utils.api_errors import parse_mexc_error
from bot.utils.bot_logging import log_command

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

        # Получаем цену с помощью метода ticker_price (проверим корректность)
        ticker = client.ticker_price(pair)
        
        # Формируем ответ пользователю
        response_text = f"Цена {pair}: {ticker['price']}"
        
        # Отправляем цену пользователю
        await message.answer(response_text)
    
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

        account_info = client.account_info()
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
                f"Доступно: {format(free, ',.2f').replace(',', 'X').replace('.', ',').replace('X', '.').replace(' ', ' ')}\n"
                f"Заморожено: {format(locked, ',.2f').replace(',', 'X').replace('.', ',').replace('X', '.').replace(' ', ' ')}"
            )

        orders = client.open_orders(symbol=pair)
        logger.info(f"Open Orders for {message.from_user.id}: {orders}")
        extra_data["open_orders_count"] = len(orders)

        total_order_amount = sum([float(order['origQty']) for order in orders])
        total_order_value = sum([float(order['price']) * float(order['origQty']) for order in orders])
        avg_price = total_order_value / total_order_amount if total_order_amount > 0 else 0

        orders_message = (
            f"\n\n📄 <b>Ордера</b>\n"
            f"Количество: {format(total_order_amount, ',.0f').replace(',', ' ')}\n"
            f"Сумма исполнения: {format(total_order_value, ',.2f').replace(',', 'X').replace('.', ',').replace('X', '.')} {quote_asset}\n"
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
        buy_order = trade_client.new_order(symbol, "BUY", "MARKET", {
            "quoteOrderQty": buy_amount
        })
        handle_mexc_response(buy_order, "Покупка через /buy")

        order_id = buy_order["orderId"]
        extra_data["buy_order_id"] = order_id

        # 2. Подтягиваем детали через query_order
        order_info = trade_client.query_order(symbol, {"orderId": order_id})
        logger.info(f"Детали ордера {order_id}: {order_info}")

        # 3. Получаем количество и среднюю цену
        executed_qty = float(order_info.get("executedQty", 0))
        if executed_qty == 0:
            response_text = "❗ Ошибка при создании ордера (executedQty=0)."
            success = False
            await message.answer(response_text)
            return

        spent = float(order_info["cummulativeQuoteQty"])  # 0.999371
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
        sell_order = trade_client.new_order(symbol, "SELL", "LIMIT", {
            "quantity": executed_qty,
            "price": f"{sell_price:.6f}",
            "timeInForce": "GTC"
        })
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
            status="SELL_ORDER_PLACED"
        )

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

        # 8. Запускаем фоновый мониторинг ордера
        asyncio.create_task(monitor_order(message, sell_order_id, user_order_number))

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
        user = await sync_to_async(User.objects.get)(telegram_id=message.from_user.id)
        extra_data["pair"] = user.pair
        extra_data["autobuy"] = user.autobuy

        header = "🔁 <b>Автобай запущен.</b>" if user.autobuy else "⚠️ <b>Автобай не запущен.</b>"

        # Получаем активные ордера
        deals_qs = Deal.objects.filter(
            user=user,
            status__in=["SELL_ORDER_PLACED", "PARTIALLY_FILLED", "NEW"]
        ).order_by("-created_at")
        active_deals = await sync_to_async(list)(deals_qs)
        extra_data["active_deals_count"] = len(active_deals)

        chunks = []
        current_chunk = header
        response_text = header
        MAX_LENGTH = 4000  # с запасом от лимита Telegram

        if active_deals:
            for deal in reversed(active_deals):  # От старых к новым
                try:
                    real_status = await sync_to_async(get_actual_order_status)(
                        user, deal.symbol, deal.order_id
                    )
                    deal.status = real_status
                    deal.save()

                    if real_status not in ["NEW", "PARTIALLY_FILLED"]:
                        continue

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

                    if len(current_chunk) + len(formatted) > MAX_LENGTH:
                        chunks.append(current_chunk)
                        current_chunk = formatted
                    else:
                        current_chunk += formatted

                except Exception as e:
                    logger.error(f"Ошибка при обработке сделки {deal.user_order_number}: {e}")
                    continue

        if current_chunk:
            chunks.append(current_chunk)

        for chunk in chunks:
            await message.answer(chunk, parse_mode="HTML")

        # Делаем краткую версию ответа для логов, если он слишком длинный
        if len(response_text) > 100:
            log_response = f"{response_text[:100]}... (показано {extra_data['active_deals_count']} ордеров)"
        else:
            log_response = response_text

    except Exception as e:
        logger.error(f"Ошибка при получении статуса для пользователя {message.from_user.id}: {e}")
        response_text = "❌ Ошибка при получении статуса."
        success = False
        await message.answer(response_text)
        extra_data["error"] = str(e)
    
    # Логируем команду и ответ
    await log_command(
        user_id=user_id,
        command=command,
        response=response_text if len(response_text) < 1000 else f"{response_text[:100]}... (сокращено)",
        success=success,
        extra_data=extra_data
    )


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

