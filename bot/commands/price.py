from aiogram import Router
from aiogram.types import Message
from aiogram.filters import Command
from users.models import User
from bot.middlewares.require_pair_middleware import RequirePairMiddleware

router = Router()
router.message.middleware(RequirePairMiddleware())

@router.message(Command("price"))
async def price_handler(message: Message):
    user = User.objects.get(telegram_id=message.from_user.id)
    pair = user.pair
    await message.answer(f"Текущая цена для {pair} — 123.45 USDT")  # Заглушка, позже вставим API
