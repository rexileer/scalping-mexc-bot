from aiogram import Router, F
from aiogram.types import Message
from aiogram.filters import Command
from bot.logger import logger
from bot.utils.bot_logging import log_command
from bot.utils.api_wrapper import log_api_request

router = Router()

# Пример использования декоратора для логирования API запросов с MEXC
@log_api_request
async def get_user_data(telegram_id):
    """
    Пример функции API, которая будет логироваться
    """
    # Имитируем запрос к API
    return {
        "status": "success",
        "user_id": telegram_id,
        "data": {
            "balance": 100.0,
            "orders": 5
        }
    }

@router.message(Command("example"))
async def handle_example_command(message: Message):
    """
    Пример обработчика команды с оптимизированным логированием
    """
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name or 'Unknown'
    command = "/example"
    
    try:
        # Выполняем запрос к API (он будет автоматически логироваться через декоратор)
        user_data = await get_user_data(telegram_id=user_id)
        
        # Формируем ответ пользователю
        response_text = f"Пример ответа команды!\n\nБаланс: {user_data['data']['balance']}\nЗаказов: {user_data['data']['orders']}"
        
        # Отправляем ответ
        await message.answer(response_text)
        
        # Логируем команду одной записью
        await log_command(
            user_id=user_id,
            command=command,
            response=response_text,
            extra_data={
                "username": username,
                "chat_id": message.chat.id,
                "balance": user_data['data']['balance'],
                "orders": user_data['data']['orders']
            }
        )
        
    except Exception as e:
        error_message = f"Error while processing {command} command: {e}"
        logger.error(error_message)
        
        # Отправляем сообщение об ошибке пользователю
        fallback_response = "Произошла ошибка при выполнении команды. Попробуйте позже."
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


# Включите этот маршрутизатор в общую структуру маршрутизаторов бота
# Например, в bot/routers/__init__.py:
# from bot.commands.example_command import router as example_router
# router.include_router(example_router) 