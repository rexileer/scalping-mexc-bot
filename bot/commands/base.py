from aiogram import Router, F
from aiogram.types import Message
from aiogram.filters import CommandStart
from bot.logger import logger
from editing.models import BotMessageForStart
from aiogram.types import FSInputFile
from bot.utils.bot_logging import log_command

router = Router()

@router.message(CommandStart())
async def bot_start(message: Message):
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name or str(user_id)
    command = "/start"
    
    try:
        # Получаем кастомное сообщение из базы
        custom_message = await BotMessageForStart.objects.afirst()
        response_text = None
        
        if custom_message:
            response_text = custom_message.text
            if custom_message.image:
                file = FSInputFile(custom_message.image.path)
                await message.answer_photo(file, custom_message.text, parse_mode="HTML")
                response_text = "Сообщение с изображением"
            else:
                await message.answer(custom_message.text)
        else:
            response_text = "Добро пожаловать в MexcBot!"
            await message.answer(response_text)
            
        # Логируем команду одной записью
        await log_command(
            user_id=user_id,
            command=command,
            response=response_text,
            extra_data={
                "username": username,
                "chat_id": message.chat.id,
                "has_custom_message": custom_message is not None,
                "has_image": custom_message and custom_message.image is not None
            }
        )
        
    except Exception as e:
        error_message = f"Error while processing {command} command: {e}"
        logger.error(error_message)
        
        # Отправляем стандартное сообщение при ошибке
        fallback_response = "Добро пожаловать в MexcBot!"
        await message.answer(fallback_response)
        
        # Логируем ошибку
        await log_command(
            user_id=user_id,
            command=command,
            response=fallback_response,
            success=False,
            extra_data={
                "username": username,
                "error": str(e)
            }
        )


