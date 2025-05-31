from aiogram import Router, F
from aiogram.types import Message
from aiogram.fsm.context import FSMContext
from asgiref.sync import sync_to_async
from .states import APIAuth
from users.models import User
from utils.mexc import check_mexc_keys
from editing.models import BotMessagesForKeys
import asyncio
from aiogram.types import FSInputFile
from logger import logger
from bot.utils.bot_logging import log_command
from aiogram.filters import Command

router = Router()

@sync_to_async
def save_api_keys(user_id: int, api_key: str, api_secret: str):
    try:
        obj, _ = User.objects.update_or_create(
            telegram_id=user_id,
            defaults={"api_key": api_key, "api_secret": api_secret}
        )
        obj.set_default_parameters()
        obj.save()
    except Exception as e:
        raise Exception(f"Ошибка при сохранении в базу данных: {e}")

@router.message(Command("set_keys"))
async def cmd_set_keys(message: Message, state: FSMContext):
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name or str(user_id)
    command = "/set_keys"
    response_text = ""
    success = True
    extra_data = {"username": username, "chat_id": message.chat.id}
    
    try:
        # Проверяем, есть ли текст для команды в БД
        db_message = await sync_to_async(lambda: BotMessagesForKeys.objects.filter(command_name="/set_keys").first())()
        
        if db_message and db_message.message_text:
            response_text = db_message.message_text
            await message.answer(response_text)
            
            # Проверяем наличие файла и отправляем, если он есть
            if db_message.image_path:
                image_path = db_message.image_path
                try:
                    await message.answer_photo(FSInputFile(image_path))
                except Exception as e:
                    logger.error(f"Ошибка при отправке изображения для /set_keys: {e}")
                    extra_data["image_error"] = str(e)
            
        else:
            # Стандартное сообщение, если нет в БД
            response_text = "Отправьте ваш <b>API Key</b> от MEXC"
            await message.answer(response_text, parse_mode="HTML")
        
        # В любом случае переводим пользователя в состояние ожидания API Key
        await state.set_state(APIAuth.waiting_for_api_key)
        
    except Exception as e:
        logger.exception(f"Ошибка при обработке команды /set_keys для {user_id}")
        response_text = f"❌ Произошла ошибка: {str(e)}"
        success = False
        await message.answer(response_text)
        extra_data["error"] = str(e)
    
    # Логируем команду и ответ
    await log_command(
        user_id=user_id,
        command=command,
        response=response_text,
        success=success,
        extra_data=extra_data
    )

@router.message(APIAuth.waiting_for_api_key)
async def get_api_key(message: Message, state: FSMContext):
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name or str(user_id)
    command = "api_key"
    response_text = ""
    success = True
    extra_data = {"username": username, "chat_id": message.chat.id}
    
    try:
        # Удаляем сообщение пользователя для безопасности
        await message.delete()
        
        api_key = message.text.strip()
        
        # Проверяем формат API ключа (примерная проверка)
        if len(api_key) < 10:
            response_text = "❌ API Key должен быть длиннее. Попробуйте снова."
            success = False
            await message.answer(response_text)
            return
        
        # Сохраняем API ключ в контексте состояния
        await state.update_data(api_key=api_key)
        
        # Запрашиваем API Secret
        response_text = "Теперь отправьте ваш <b>Secret Key</b>"
        await message.answer(response_text, parse_mode="HTML")
        
        # Переходим к следующему состоянию
        await state.set_state(APIAuth.waiting_for_api_secret)
        
    except Exception as e:
        logger.exception(f"Ошибка при получении API Key для {user_id}")
        response_text = f"❌ Произошла ошибка: {str(e)}"
        success = False
        await message.answer(response_text)
        extra_data["error"] = str(e)
    
    # Логируем команду и ответ
    await log_command(
        user_id=user_id,
        command=command,
        response=response_text,
        success=success,
        extra_data=extra_data
    )

@router.message(APIAuth.waiting_for_api_secret)
async def get_api_secret(message: Message, state: FSMContext):
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name or str(user_id)
    command = "api_secret"
    response_text = ""
    success = True
    extra_data = {"username": username, "chat_id": message.chat.id}
    
    try:
        # Удаляем сообщение пользователя для безопасности
        await message.delete()
        
        # Получаем API secret
        api_secret = message.text.strip()
        
        # Проверяем формат Secret Key (примерная проверка)
        if len(api_secret) < 10:
            response_text = "❌ Secret Key должен быть длиннее. Попробуйте снова."
            success = False
            await message.answer(response_text)
            return
        
        # Получаем сохраненный API key из контекста
        data = await state.get_data()
        api_key = data.get("api_key")
        
        # Проверяем ключи через тестовый запрос к API
        valid, error_message = await check_mexc_keys(api_key, api_secret)
        
        if not valid:
            response_text = f"❌ Неверные ключи API: {error_message}"
            success = False
            await message.answer(response_text)
            # Сбрасываем состояние
            await state.clear()
            return
        
        # Сохранение API ключей в базе данных
        try:
            await save_api_keys(message.from_user.id, api_key, api_secret)
            
            # Инициализируем WebSocket соединение для пользователя
            # Импортируем websocket_manager внутри функции
            from bot.utils.websocket_manager import websocket_manager
            websocket_init_task = asyncio.create_task(websocket_manager.connect_user_data_stream(message.from_user.id))
            extra_data["websocket_init"] = True
            
            response_text = "✅ Ключи успешно сохранены.\nДля запуска бота нажмите команду /start"
            await message.answer(response_text)
            extra_data["keys_saved"] = True
        except Exception as e:
            logger.error(f"Ошибка при сохранении ключей: {e}")
            response_text = f"❌ Ошибка при сохранении ключей: {str(e)}"
            success = False
            await message.answer(response_text)
            extra_data["db_error"] = str(e)
        
        # Сбрасываем состояние
        await state.clear()
        
    except Exception as e:
        logger.exception(f"Ошибка при получении API Secret для {user_id}")
        response_text = f"❌ Произошла ошибка: {str(e)}"
        success = False
        await message.answer(response_text)
        await state.clear()
        extra_data["error"] = str(e)
    
    # Логируем команду и ответ
    await log_command(
        user_id=user_id,
        command=command,
        response=response_text,
        success=success,
        extra_data=extra_data
    )
