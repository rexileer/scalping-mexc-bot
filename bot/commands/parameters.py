from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.fsm.context import FSMContext
from asgiref.sync import sync_to_async
from .states import ParameterChange
from users.models import User
from bot.logger import logger
from bot.keyboards.inline import build_parameters_keyboard

router = Router()

# Команда для отображения параметров
@router.message(F.text == "/parameters")
async def show_parameters(message: Message, state: FSMContext):
    await state.clear()
    user_params = await get_user_parameters(message.from_user.id)
    if not user_params:
        await message.answer("Пользователь не найден в базе данных.")
        return

    keyboard = build_parameters_keyboard(user_params)
    await message.answer("Выберите параметр для изменения:", reply_markup=keyboard)



async def handle_param_change(callback_query: CallbackQuery, state: FSMContext, text: str, state_to_set):
    await callback_query.message.edit_text(text)
    await state.set_state(state_to_set)
    await callback_query.answer()


@router.callback_query(F.data == "change_profit")
async def change_profit(callback_query: CallbackQuery, state: FSMContext):
    await handle_param_change(callback_query, state, "Введите новую прибыль (например, 5.5):", ParameterChange.waiting_for_profit)


@router.callback_query(F.data == "change_loss")
async def change_loss(callback_query: CallbackQuery, state: FSMContext):
    await handle_param_change(callback_query, state, "Введите новое падение (например, 3.5):", ParameterChange.waiting_for_loss)


@router.callback_query(F.data == "change_pause")
async def change_pause(callback_query: CallbackQuery, state: FSMContext):
    await handle_param_change(callback_query, state, "Введите новую паузу (целое число):", ParameterChange.waiting_for_pause)


@router.callback_query(F.data == "change_buy_amount")
async def change_buy_amount(callback_query: CallbackQuery, state: FSMContext):
    await handle_param_change(callback_query, state, "Введите новую сумму покупки (например, 100):", ParameterChange.waiting_for_buy_amount)


async def finalize_parameter_change(message: Message, state: FSMContext, field: str, parser):
    try:
        value = parser(message.text)
        await save_user_parameter(message.from_user.id, field, value)
        user_params = await get_user_parameters(message.from_user.id)
        keyboard = build_parameters_keyboard(user_params)
        await message.answer(f"[OK] {field} обновлён: {value}", reply_markup=keyboard)
    except ValueError:
        await message.answer("❌ Некорректное значение. Попробуйте снова.")
    finally:
        await state.clear()


@router.message(ParameterChange.waiting_for_profit)
async def set_profit(message: Message, state: FSMContext):
    await finalize_parameter_change(message, state, 'profit', float)

@router.message(ParameterChange.waiting_for_loss)
async def set_loss(message: Message, state: FSMContext):
    await finalize_parameter_change(message, state, 'loss', float)

@router.message(ParameterChange.waiting_for_pause)
async def set_pause(message: Message, state: FSMContext):
    await finalize_parameter_change(message, state, 'pause', int)

@router.message(ParameterChange.waiting_for_buy_amount)
async def set_buy_amount(message: Message, state: FSMContext):
    await finalize_parameter_change(message, state, 'buy_amount', float)


# Получение параметров
@sync_to_async
def get_user_parameters(user_id: int):
    try:
        return User.objects.get(telegram_id=user_id)
    except User.DoesNotExist:
        logger.warning(f"User {user_id} not found")
        return None


@sync_to_async
def save_user_parameter(user_id: int, param: str, value: float):
    try:
        user = User.objects.get(telegram_id=user_id)
        setattr(user, param, value)
        user.save()
        logger.info(f"[OK] Saved {param}={value} for user {user_id}")
    except User.DoesNotExist:
        logger.error(f"❌ Cannot save {param} — user {user_id} not found")
