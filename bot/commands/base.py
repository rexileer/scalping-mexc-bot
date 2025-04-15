from aiogram import Router, F
from aiogram.types import Message
from aiogram.filters import CommandStart
from bot.logger import logger
from editing.models import BotMessageForStart

router = Router()

@router.message(CommandStart())
async def bot_start(message: Message):
    logger.info(f"User {message.from_user.id} started bot")
    try:
        # Получаем кастомное сообщение из базы
        custom_message = await BotMessageForStart.objects.afirst()
        if custom_message:
            await message.answer(custom_message.text)
        else:
            await message.answer("Добро пожаловать в MexcBot!")
    except Exception as e:
        logger.error(f"Error while fetching start message: {e}")
        # Если произошла ошибка, отправляем стандартное сообщение
        await message.answer("Добро пожаловать в MexcBot!")


