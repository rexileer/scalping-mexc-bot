from aiogram import Router
from aiogram.types import Message
from aiogram.filters import Command

from bot.middlewares.require_pair_middleware import RequirePairMiddleware
from bot.utils.mexc import get_user_client
from users.models import User
from logger import logger

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

# /balance
@router.message(Command("balance"))
async def balance_handler(message: Message):
    try:
        user = User.objects.get(telegram_id=message.from_user.id)
        client, pair = get_user_client(message.from_user.id)  # Получаем клиента

        # Получаем информацию о аккаунте
        account_info = client.account_info()

        # Логируем информацию о балансе
        logger.info(f"Account Info for {message.from_user.id}: {account_info}")

        # Формируем строку с балансами
        balances_message = "💰 Ваш баланс:\n"
        for balance in account_info['balances']:
            asset = balance['asset']
            free = float(balance['free'])
            locked = float(balance['locked'])

            if free > 0 or locked > 0:  # Выводим только те валюты, у которых есть средства
                balances_message += f"\n{asset}\nДоступно: {free:.2f}\nЗаморожено: {locked:.2f}"

        # Получаем информацию о ордерах
        orders = client.open_orders(symbol=pair)  # Получаем открытые ордера по текущей паре

        # Логируем информацию о ордерах
        logger.info(f"Open Orders for {message.from_user.id}: {orders}")

        total_order_amount = sum([float(order['origQty']) for order in orders])
        total_order_value = sum([float(order['price']) * float(order['origQty']) for order in orders])
        avg_price = total_order_value / total_order_amount if total_order_amount > 0 else 0

        orders_message = f"\n\nОрдера\nКоличество: {total_order_amount:.2f}\nСумма исполнения: {total_order_value:.2f} USDT\nСредняя цена исполнения: {avg_price:.6f} USDT"

        # Отправляем сообщение пользователю
        await message.answer(balances_message + orders_message)

        logger.info(f"User {user.telegram_id} requested balance and orders.")
    
    except Exception as e:
        logger.error(f"Ошибка при получении баланса для пользователя {message.from_user.id}: {e}")
        await message.answer("Произошла ошибка при получении баланса.")


# /buy
@router.message(Command("buy"))
async def buy_handler(message: Message):
    try:
        user = User.objects.get(telegram_id=message.from_user.id)
        # Отправляем информацию о покупке
        await message.answer(f"✅ Покупка по паре {user.pair} выполнена (заглушка)")
        logger.info(f"User {user.telegram_id} made a buy request for {user.pair}.")
    except Exception as e:
        logger.error(f"Ошибка при выполнении покупки для пользователя {message.from_user.id}: {e}")
        await message.answer("Произошла ошибка при выполнении покупки.")

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
async def stats_handler(message: Message):
    try:
        user = User.objects.get(telegram_id=message.from_user.id)
        # Отправляем статистику по покупкам
        await message.answer(f"📈 Ваша статистика по {user.pair}:\n- Покупок: 5\n- Средняя цена: 120.00 USDT (заглушка)")
        logger.info(f"User {user.telegram_id} requested stats for {user.pair}.")
    except Exception as e:
        logger.error(f"Ошибка при получении статистики для пользователя {message.from_user.id}: {e}")
        await message.answer("Произошла ошибка при получении статистики.")