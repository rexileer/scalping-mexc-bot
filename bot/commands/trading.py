from aiogram import Router
from aiogram.types import Message
from aiogram.filters import Command

from bot.middlewares.require_pair_middleware import RequirePairMiddleware
from users.models import User

router = Router()
router.message.middleware(RequirePairMiddleware())

# /price
@router.message(Command("price"))
async def price_handler(message: Message):
    user = User.objects.get(telegram_id=message.from_user.id)
    pair = user.pair
    await message.answer(f"📈 Текущая цена {pair} — 123.45 USDT (заглушка)")

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
