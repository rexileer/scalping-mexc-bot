from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.filters import Command
from users.models import User

router = Router()

# Команда /pair
@router.message(Command("pair"))
async def pair(message: Message):
    # Создаем инлайн кнопки для двух торговых пар
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="KAS/USDT", callback_data="pair_KAS_USDT")],
        [InlineKeyboardButton(text="BTC/USDC", callback_data="pair_BTC_USDC")],
    ])

    # Отправка сообщения с клавиатурой
    await message.answer("Выберите торговую пару:", reply_markup=keyboard)

# Обработка выбора торговой пары
@router.callback_query(F.data.startswith("pair_"))
async def process_pair_selection(callback_query: CallbackQuery):
    # Получаем торговую пару из callback_data
    selected_pair = callback_query.data.split('_')[1]  # Получаем KAS_USDT или BTC_USDC

    # Обновляем выбранную пару в базе данных для пользователя
    try:
        user = User.objects.get(telegram_id=callback_query.from_user.id)
        user.pair = selected_pair
        user.save()
        await callback_query.answer(f"Вы выбрали торговую пару: {selected_pair}")
        await callback_query.message.answer(f"Теперь ваша торговая пара: {selected_pair}")
    except Exception as e:
        await callback_query.answer(f"Произошла ошибка: {e}")