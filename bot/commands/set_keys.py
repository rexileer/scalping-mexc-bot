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

router = Router()

@router.message(F.text == "/set_keys")
async def start_setting_keys(message: Message, state: FSMContext):
    try:
        bot_message = await BotMessagesForKeys.objects.afirst()
        if bot_message:
            if bot_message.access_image:
                file = FSInputFile(bot_message.access_image.path)
                await message.answer_photo(file, bot_message.access_key, parse_mode="HTML")
            else:
                await message.answer(bot_message.access_key)
        else:
            await message.answer("Введите ваш API Key:")
    except Exception as e:
        await message.answer("Введите ваш API Key:")
    finally:
        await state.set_state(APIAuth.waiting_for_api_key)

@router.message(APIAuth.waiting_for_api_key)
async def get_api_key(message: Message, state: FSMContext):
    await state.update_data(api_key=message.text)
    try:
        bot_message = await BotMessagesForKeys.objects.afirst()
        if bot_message:
            if bot_message.secret_image:
                file = FSInputFile(bot_message.secret_image.path)
                await message.answer_photo(file, bot_message.secret_key, parse_mode="HTML")
            else:
                await message.answer(bot_message.secret_key)
        else:
            await message.answer("Теперь введите ваш API Secret:")
    except Exception as e:
        await message.answer("Теперь введите ваш API Secret:")
    finally:
        await state.set_state(APIAuth.waiting_for_api_secret)

@router.message(APIAuth.waiting_for_api_secret)
async def get_api_secret(message: Message, state: FSMContext):
    data = await state.get_data()
    api_key = data["api_key"]
    api_secret = message.text

    # Проверка правильности API ключей
    try:
        is_valid = await asyncio.to_thread(check_mexc_keys, api_key, api_secret)
        if not is_valid:
            await message.answer("❌ Неверные API ключи. Попробуйте снова с командой /set_keys")
            await state.clear()
            return
    except Exception as e:
        await message.answer(f"Произошла ошибка при проверке ключей: {e}")
        await state.clear()
        return

    # Сохранение API ключей в базе данных
    try:
        await save_api_keys(message.from_user.id, api_key, api_secret)
        await message.answer("✅ Ключи успешно сохранены.")
    except Exception as e:
        await message.answer(f"Ошибка при сохранении ключей: {e}")
    finally:
        await state.clear()

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
