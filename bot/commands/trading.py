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
    user = User.objects.get(telegram_id=message.from_user.id)
    await message.answer(f"💰 Ваш баланс: 1000 USDT (заглушка)")

# /buy
@router.message(Command("buy"))
async def buy_handler(message: Message):
    user = User.objects.get(telegram_id=message.from_user.id)
    await message.answer(f"✅ Покупка по паре {user.pair} выполнена (заглушка)")

# /auto_buy
@router.message(Command("autobuy"))
async def auto_buy_handler(message: Message):
    user = User.objects.get(telegram_id=message.from_user.id)
    await message.answer(f"🤖 Автопокупка по паре {user.pair} активирована (заглушка)")

# /status
@router.message(Command("status"))
async def status_handler(message: Message):
    user = User.objects.get(telegram_id=message.from_user.id)
    await message.answer(f"📊 Статус отслеживания по {user.pair}: активен (заглушка)")

# /stats
@router.message(Command("stats"))
async def stats_handler(message: Message):
    user = User.objects.get(telegram_id=message.from_user.id)
    await message.answer(f"📈 Ваша статистика по {user.pair}:\n- Покупок: 5\n- Средняя цена: 120.00 USDT (заглушка)")
