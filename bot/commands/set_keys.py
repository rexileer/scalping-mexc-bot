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

router = Router()

@router.message(F.text == "/set_keys")
async def start_setting_keys(message: Message, state: FSMContext):
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name or str(user_id)
    command = "/set_keys"
    response_text = ""
    success = True
    extra_data = {"username": username, "chat_id": message.chat.id}
    
    try:
        bot_message = await BotMessagesForKeys.objects.afirst()
        extra_data["has_custom_message"] = bot_message is not None
        
        if bot_message:
            if bot_message.access_image:
                file = FSInputFile(bot_message.access_image.path)
                response_text = bot_message.access_key
                extra_data["has_image"] = True
                await message.answer_photo(file, response_text, parse_mode="HTML")
            else:
                response_text = bot_message.access_key
                await message.answer(response_text)
        else:
            response_text = "Введите ваш API Key:"
            await message.answer(response_text)
    except Exception as e:
        logger.exception(f"Ошибка при запросе API key для {user_id}")
        response_text = "Введите ваш API Key:"
        success = False
        extra_data["error"] = str(e)
        await message.answer(response_text)
    finally:
        # Устанавливаем состояние ожидания API ключа
        await state.set_state(APIAuth.waiting_for_api_key)
        
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
    command = "api_key_input"
    response_text = ""
    success = True
    extra_data = {
        "username": username, 
        "chat_id": message.chat.id,
        "state": "waiting_for_api_key",
        "api_key_length": len(message.text) if message.text else 0
    }
    
    try:
        # Сохраняем API ключ в данных состояния
        await state.update_data(api_key=message.text)
        
        # Проверяем, есть ли кастомное сообщение
        bot_message = await BotMessagesForKeys.objects.afirst()
        extra_data["has_custom_message"] = bot_message is not None
        
        if bot_message:
            if bot_message.secret_image:
                file = FSInputFile(bot_message.secret_image.path)
                response_text = bot_message.secret_key
                extra_data["has_image"] = True
                await message.answer_photo(file, response_text, parse_mode="HTML")
            else:
                response_text = bot_message.secret_key
                await message.answer(response_text)
        else:
            response_text = "Теперь введите ваш API Secret:"
            await message.answer(response_text)
    except Exception as e:
        logger.exception(f"Ошибка при обработке API key для {user_id}")
        response_text = "Теперь введите ваш API Secret:"
        success = False
        extra_data["error"] = str(e)
        await message.answer(response_text)
    finally:
        # Устанавливаем состояние ожидания Secret
        await state.set_state(APIAuth.waiting_for_api_secret)
        
        # Логируем обработку API ключа
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
    command = "api_secret_input"
    response_text = ""
    success = True
    extra_data = {
        "username": username, 
        "chat_id": message.chat.id,
        "state": "waiting_for_api_secret",
        "api_secret_length": len(message.text) if message.text else 0
    }
    
    try:
        data = await state.get_data()
        api_key = data["api_key"]
        api_secret = message.text

        # Проверка правильности API ключей
        try:
            is_valid, error_text = await asyncio.to_thread(check_mexc_keys, api_key, api_secret)
            extra_data["keys_valid"] = is_valid
            
            if not is_valid:
                response_text = f"❌ {error_text}\n\n Попробуйте снова с командой /set_keys"
                await message.answer(response_text)
                success = False
                extra_data["validation_error"] = error_text
                await state.clear()
                
                # Логируем результат проверки
                await log_command(
                    user_id=user_id,
                    command=command,
                    response=response_text,
                    success=success,
                    extra_data=extra_data
                )
                return
        except Exception as e:
            response_text = f"Произошла ошибка при проверке ключей: {e}"
            await message.answer(response_text)
            success = False
            extra_data["error"] = str(e)
            await state.clear()
            
            # Логируем ошибку
            await log_command(
                user_id=user_id,
                command=command,
                response=response_text,
                success=success,
                extra_data=extra_data
            )
            return

        # Сохранение API ключей в базе данных
        try:
            await save_api_keys(message.from_user.id, api_key, api_secret)
            response_text = "✅ Ключи успешно сохранены.\nДля запуска бота нажмите команду /start"
            await message.answer(response_text)
            extra_data["keys_saved"] = True
        except Exception as e:
            response_text = f"Ошибка при сохранении ключей: {e}"
            await message.answer(response_text)
            success = False
            extra_data["error"] = str(e)
    except Exception as e:
        logger.exception(f"Ошибка при обработке API secret для {user_id}")
        response_text = f"Произошла непредвиденная ошибка: {e}"
        success = False
        extra_data["error"] = str(e)
        await message.answer(response_text)
    finally:
        await state.clear()
        
        # Логируем результат сохранения ключей
        await log_command(
            user_id=user_id,
            command=command,
            response=response_text,
            success=success,
            extra_data=extra_data
        )

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
