from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command, CommandStart
import re
from bot.logger import logger
from bot.utils.bot_logging import log_command, log_user_action, log_callback

router = Router()

# Паттерн для определения команд: "/" + 1 или более букв/цифр/подчеркиваний
COMMAND_PATTERN = re.compile(r'^/[a-zA-Z0-9_]+')

# Обработчик для команд, которые не были обработаны другими хендлерами
@router.message(lambda message: message.text and COMMAND_PATTERN.match(message.text) and not message.text.startswith(('/start', '/set_keys', '/faq', '/subscription', '/parameters', '/price', '/buy', '/auto_buy', '/autobuy', '/balance', '/status', '/stats')))
async def handle_unknown_command(message: Message):
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name or str(user_id)
    command = message.text.split()[0] if message.text else "/unknown"
    
    # Отправляем ответ об неизвестной команде
    response_text = f"Неизвестная команда: {command}."
    await message.answer(response_text)
    
    # Логируем неизвестную команду
    await log_command(
        user_id=user_id,
        command=command,
        response=response_text,
        extra_data={
            "username": username,
            "chat_id": message.chat.id,
            "full_text": message.text,
            "status": "unknown_command"
        }
    )
    
    logger.info(f"User {user_id} sent unknown command: {command}")

# Обработчик для всех остальных типов сообщений, которые не были обработаны
@router.message()
async def handle_other_messages(message: Message):
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name or str(user_id)
    
    # Для текстовых сообщений
    if message.content_type == 'text':
        text = message.text
        
        # Логирование уже происходит в middleware, поэтому здесь мы просто отвечаем
        response_text = "Для взаимодействия с ботом используйте команды."
        await message.answer(response_text)
        
        logger.info(f"User {user_id} sent unhandled text message: {text[:50]}...")
    
    # Для нетекстовых сообщений (фото, видео, документы и т.д.)
    else:
        # Отвечаем, что бот не обрабатывает этот тип контента
        response_text = f"Бот не поддерживает обработку контента типа: {message.content_type}"
        await message.answer(response_text)
        
        logger.info(f"User {user_id} sent unhandled {message.content_type}")
        
        # Этот лог уже создан в middleware, здесь мы не дублируем

# Обработчик для необработанных callback-запросов (нажатия на кнопки)
@router.callback_query()
async def handle_unknown_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    username = callback.from_user.username or callback.from_user.first_name or str(user_id)
    
    # Отвечаем пользователю
    await callback.answer("Действие не поддерживается или устарело")
    
    # Логирование уже происходит в middleware, поэтому здесь мы только логируем в консоль
    logger.warning(f"User {user_id} sent unhandled callback with data: {callback.data}") 