from aiogram import Router, F
from aiogram.types import Message
from aiogram.filters import Command
import asyncio
from bot.commands.buy import monitor_order
from bot.middlewares.require_pair_middleware import RequirePairMiddleware
from bot.utils.mexc import get_user_client
from users.models import User, Deal
from logger import logger
from bot.keyboards.inline import get_period_keyboard
from asgiref.sync import sync_to_async
from mexc_sdk import Trade  # Предполагаем, что именно этот класс отвечает за торговые операции


router = Router()
router.message.middleware(RequirePairMiddleware())

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


import locale
# Устанавливаем русскую локаль для форматирования чисел
locale.setlocale(locale.LC_ALL, 'ru_RU.UTF-8')  # может не работать на Windows, тогда использовать кастомную функцию

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
            f"Сумма исполнения: {format(total_order_value, ',.2f').replace(',', 'X').replace('.', ',').replace('X', '.').replace(' ', ' ')} USDT\n"
            f"Средняя цена исполнения: {format(avg_price, ',.6f').replace(',', 'X').replace('.', ',').replace('X', '.')} USDT"
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

        # 1. ПОКУПКА по рынку на сумму
        buy_order = trade_client.new_order_test(symbol, "BUY", "MARKET", {
            "quoteOrderQty": buy_amount
        })

        # 2. Получаем данные из ордера
        executed_qty = float(buy_order["executedQty"])  # сколько купили
        avg_price = float(buy_order["fills"][0]["price"])  # по какой цене
        # executed_qty = 100  # заглушка
        # avg_price = 120  # заглушка


        spent = executed_qty * avg_price  # фактически потрачено

        # 3. Считаем цену продажи
        profit_percent = float(user.profit)
        sell_price = round(avg_price * (1 + profit_percent / 100), 6)

        # 4. ВЫСТАВЛЯЕМ лимитный SELL ордер
        sell_order = trade_client.new_order_test(symbol, "SELL", "LIMIT", {
            "quantity": executed_qty,
            "price": f"{sell_price:.6f}",
            "timeInForce": "GTC"
        })
        # Сохраняем ордер в базе данных как покупку
        order_id = sell_order['orderId']
        deal = await sync_to_async(Deal.objects.create)(
            user=user,
            order_id=order_id,
            symbol=symbol,
            buy_price=avg_price,  # Цена покупки
            quantity=executed_qty,
            status="BUY_ORDER_PLACED"
        )

        # Обновляем ордер на продажу в базе данных
        deal.sell_price = sell_price
        deal.status = "SELL_ORDER_PLACED"
        deal.save()

        # 5. Формируем красивый ответ
        text = (
            f"✅ КУПЛЕНО\n\n"
            f"{executed_qty:.2f} {symbol[:-4]} по {avg_price:.6f} USDT\n\n"
            f"Потрачено\n"
            f"{spent:.8f} USDT\n\n"
            f"📈 ВЫСТАВЛЕНО\n\n"
            f"{executed_qty:.2f} {symbol[:-4]} по {sell_price:.6f} USDT"
        )
        await message.answer(text)

        logger.info(f"BUY + SELL for {user.telegram_id}: {executed_qty} {symbol} @ {avg_price} -> {sell_price}")
        # 4. Запускаем фоновый мониторинг ордера
        asyncio.create_task(monitor_order(message, order_id))
        logger.info(f"Monitoring order {buy_order['orderId']} for user {user.telegram_id}.")
    except Exception as e:
        logger.error(f"Ошибка при /buy для {message.from_user.id}: {e}")
        await message.answer("❌ Ошибка при выполнении сделки.")



# /auto_buy
@router.message(Command("autobuy"))
async def auto_buy_handler(message: Message):
    try:
        user = User.objects.get(telegram_id=message.from_user.id)
        # Активируем автопокупку
        await message.answer(f"🤖 Автопокупка по паре {user.pair} активирована (заглушка)")
        logger.info(f"User {user.telegram_id} activated auto-buy for {user.pair}.")
    except Exception as e:
        logger.error(f"Ошибка при активации автопокупки для пользователя {message.from_user.id}: {e}")
        await message.answer("Произошла ошибка при активации автопокупки.")

# /status
@router.message(Command("status"))
async def status_handler(message: Message):
    try:
        user = User.objects.get(telegram_id=message.from_user.id)
        # Отправляем статус отслеживания
        await message.answer(f"📊 Статус отслеживания по {user.pair}: активен (заглушка)")
        logger.info(f"User {user.telegram_id} requested status for {user.pair}.")
    except Exception as e:
        logger.error(f"Ошибка при получении статуса для пользователя {message.from_user.id}: {e}")
        await message.answer("Произошла ошибка при получении статуса.")


# /stats
@router.message(Command("stats"))
async def ask_stats_period(message: Message):
    await message.answer("Выберите период для статистики:", reply_markup=get_period_keyboard())

