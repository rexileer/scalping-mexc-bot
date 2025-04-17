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
from bot.utils.mexc import handle_mexc_response
from bot.utils.api_errors import parse_mexc_error


router = Router()

# /price
@router.message(Command("price"))
async def get_user_price(message: Message):
    try:
        # Получаем клиента и пару для пользователя
        client, pair = get_user_client(message.from_user.id)

        # Проверяем, что валидная пара получена
        if not pair:
            raise ValueError("Валютная пара не указана.")

        # Получаем цену с помощью метода ticker_price (проверим корректность)
        ticker = client.ticker_price(pair)
        
        # Отправляем цену пользователю
        await message.answer(f"Цена {pair}: {ticker['price']}")
    
    except ValueError as e:
        # Обрабатываем ошибки, если ошибка в API или данных
        await message.answer(f"Ошибка: {e}")
    except Exception as e:
        # Логируем и отправляем пользователю общую ошибку
        logger.error(f"Произошла ошибка при получении цены: {e}")
        await message.answer("Произошла ошибка при получении цены.")


@router.message(Command("balance"))
async def balance_handler(message: Message):
    try:
        user = User.objects.get(telegram_id=message.from_user.id)
        client, pair = get_user_client(message.from_user.id)

        account_info = client.account_info()
        logger.info(f"Account Info for {message.from_user.id}: {account_info}")

        balances_message = "💰 <b>БАЛАНС</b>\n"

        for balance in account_info['balances']:
            asset = balance['asset']
            free = float(balance['free'])
            locked = float(balance['locked'])

            if free > 0 or locked > 0:
                balances_message += (
                    f"\n<b>{asset}</b>\n"
                    f"Доступно: {format(free, ',.2f').replace(',', 'X').replace('.', ',').replace('X', '.').replace(' ', ' ')}\n"
                    f"Заморожено: {format(locked, ',.2f').replace(',', 'X').replace('.', ',').replace('X', '.').replace(' ', ' ')}"
                )

        orders = client.open_orders(symbol=pair)
        logger.info(f"Open Orders for {message.from_user.id}: {orders}")

        total_order_amount = sum([float(order['origQty']) for order in orders])
        total_order_value = sum([float(order['price']) * float(order['origQty']) for order in orders])
        avg_price = total_order_value / total_order_amount if total_order_amount > 0 else 0

        orders_message = (
            f"\n\n📄 <b>Ордера</b>\n"
            f"Количество: {format(total_order_amount, ',.0f').replace(',', ' ')}\n"
            f"Сумма исполнения: {format(total_order_value, ',.2f').replace(',', 'X').replace('.', ',').replace('X', '.').replace(' ', ' ')} USDT/USDC\n"
            f"Средняя цена исполнения: {format(avg_price, ',.6f').replace(',', 'X').replace('.', ',').replace('X', '.')} USDT/USDC"
        )

        await message.answer(balances_message + orders_message, parse_mode="HTML")
        logger.info(f"User {user.telegram_id} requested balance and orders.")
    
    except Exception as e:
        logger.error(f"Ошибка при получении баланса для пользователя {message.from_user.id}: {e}")
        await message.answer("Произошла ошибка при получении баланса.")

# /buy
@router.message(Command("buy"))
async def buy_handler(message: Message):
    try:
        user = User.objects.get(telegram_id=message.from_user.id)

        if not user.pair:
            await message.answer("❗ Вы не выбрали торговую пару. Введите /pair для выбора.")
            return

        symbol = user.pair.replace("/", "")
        trade_client = Trade(api_key=user.api_key, api_secret=user.api_secret)
        buy_amount = float(user.buy_amount)

        # 1. Создаём ордер
        buy_order = trade_client.new_order(symbol, "BUY", "MARKET", {
            "quoteOrderQty": buy_amount
        })
        handle_mexc_response(buy_order, "Покупка через /buy")

        order_id = buy_order["orderId"]

        # 2. Подтягиваем детали через query_order
        order_info = trade_client.query_order(symbol, {"orderId": order_id})
        logger.info(f"Детали ордера {order_id}: {order_info}")

        # 3. Получаем количество и среднюю цену
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

        # 5. Выставляем лимитный SELL ордер
        sell_order = trade_client.new_order(symbol, "SELL", "LIMIT", {
            "quantity": executed_qty,
            "price": f"{sell_price:.6f}",
            "timeInForce": "GTC"
        })
        handle_mexc_response(sell_order, "Продажа")
        sell_order_id = sell_order["orderId"]
        logger.info(f"SELL ордер {sell_order_id} выставлен на {sell_price:.6f} {symbol[3:]}")

        # 6. Сохраняем ордер в базу
        # Получаем следующий номер
        last_number = await sync_to_async(
            lambda: Deal.objects.filter(user=user).count()
        )()
        user_order_number = last_number + 1
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
        text = (
            f"✅ <b>КУПЛЕНО</b>\n\n"
            f"{executed_qty:.2f} {symbol[:3]} по {real_price:.6f} {symbol[3:]}\n\n"
            f"<b>Потрачено</b>\n"
            f"{spent:.8f} {symbol[3:]}\n\n"
            f"📈 <b>ВЫСТАВЛЕНО</b>\n\n"
            f"{executed_qty:.2f} {symbol[:3]} по {sell_price:.6f} {symbol[3:]}"
        )
        await message.answer(text, parse_mode='HTML')

        logger.info(f"BUY + SELL for {user.telegram_id}: {executed_qty} {symbol} @ {real_price} -> {sell_price}")

        # 8. Запускаем фоновый мониторинг ордера
        asyncio.create_task(monitor_order(message, sell_order_id, user_order_number))

    except Exception as e:
        logger.exception("Ошибка при выполнении /buy")
        user_message = f"❌ {parse_mexc_error(e)}"
        await message.answer(user_message)


# /auto_buy
@router.message(Command("autobuy"))
async def autobuy_handler(message: Message):
    telegram_id = message.from_user.id
    user = await sync_to_async(User.objects.get)(telegram_id=telegram_id)

    if user.autobuy:
        await message.answer("⚠️ Автобай уже запущен. Остановить: /stop")
        return

    user.autobuy = True
    await sync_to_async(user.save)()

    task = asyncio.create_task(autobuy_loop(message, telegram_id))
    user_autobuy_tasks[telegram_id] = task

    await message.answer("🔁 Автобай запущен. Остановить: /stop")


@router.message(Command("stop"))
async def stop_autobuy(message: Message):
    telegram_id = message.from_user.id
    user = await sync_to_async(User.objects.get)(telegram_id=telegram_id)

    task = user_autobuy_tasks.get(telegram_id)

    if user.autobuy:
        user.autobuy = False
        await sync_to_async(user.save)()

        if task:
            task.cancel()
            del user_autobuy_tasks[telegram_id]

        await message.answer("⛔ Автобай остановлен.")
    else:
        await message.answer("⚠️ Автобай не был запущен.")


# /status
@router.message(Command("status"))
async def status_handler(message: Message):
    telegram_id = message.from_user.id
    try:
        user = await sync_to_async(User.objects.get)(telegram_id=telegram_id)

        if not user.autobuy:
            await message.answer("⏸ AutoBuy не запущен.")
            return

        last_deal = await sync_to_async(
            lambda: Deal.objects.filter(user=user, is_autobuy=True).order_by("-created_at").first()
        )()

        if not last_deal:
            await message.answer("🔁 AutoBuy запущен.\nОжидается первая сделка...")
            return

        updated = localtime(last_deal.updated_at).strftime('%d.%m %H:%M')

        status_text = {
            "SELL_ORDER_PLACED": "⏳ Ожидает продажи",
            "FILLED": "✅ Сделка исполнена",
            "CANCELLED": "❌ Отменена",
        }.get(last_deal.status, f"📌 Статус: {last_deal.status}")

        text = (
            f"🔁 *AutoBuy активен*\n"
            f"Пара: *{last_deal.symbol}*\n\n"
            f"{status_text}\n"
            f"{last_deal.quantity:.4f} {last_deal.symbol[:3]} по {last_deal.sell_price:.4f} {last_deal.symbol[3:]}\n"
            f"Обновлено: {updated}"
        )

        await message.answer(text, parse_mode="Markdown")
        logger.info(f"User {telegram_id} requested autobuy status.")
        
    except Exception as e:
        logger.error(f"Ошибка при получении статуса для пользователя {telegram_id}: {e}")
        await message.answer("❌ Ошибка при получении статуса.")


# /stats
@router.message(Command("stats"))
async def ask_stats_period(message: Message):
    await message.answer("Выберите период для статистики:", reply_markup=get_period_keyboard())

