from aiogram import Router, F
from aiogram.types import Message
from aiogram.fsm.context import FSMContext
from .states import APIAuth
from users.models import User  
from asgiref.sync import sync_to_async

router = Router()

@router.message(F.text == "/set_keys")
async def start_setting_keys(message: Message, state: FSMContext):
    await message.answer("Введите ваш API Key:")
    await state.set_state(APIAuth.waiting_for_api_key)

@router.message(APIAuth.waiting_for_api_key)
async def get_api_key(message: Message, state: FSMContext):
    await state.update_data(api_key=message.text)
    await message.answer("Теперь введите ваш API Secret:")
    await state.set_state(APIAuth.waiting_for_api_secret)

@router.message(APIAuth.waiting_for_api_secret)
async def get_api_secret(message: Message, state: FSMContext):
    data = await state.get_data()
    api_key = data["api_key"]
    api_secret = message.text

    # Сохраняем ключи (можно добавить проверку их валидности)
    await save_api_keys(message.from_user.id, api_key, api_secret)
    await message.answer("Ключи сохранены. Можете использовать команды.")
    await state.clear()

@sync_to_async
def save_api_keys(user_id: int, api_key: str, api_secret: str):
    obj, _ = User.objects.update_or_create(
        telegram_id=user_id,
        defaults={"api_key": api_key, "api_secret": api_secret}
    )
