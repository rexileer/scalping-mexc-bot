from aiogram import Router, F
from aiogram.types import Message
from aiogram.filters import CommandStart
from bot.logger import logger

router = Router()

@router.message(CommandStart())
async def bot_start(message: Message):
    logger.info(f"User {message.from_user.id} started bot")
    await message.answer("Добро пожаловать в MexcBot!")


