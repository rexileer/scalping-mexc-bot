from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.fsm.context import FSMContext
from asgiref.sync import sync_to_async
from .states import ParameterChange
from users.models import User
from bot.logger import logger

router = Router()

# Команда для отображения параметров
@router.message(F.text == "/parameters")
async def show_parameters(message: Message, state: FSMContext):
    await state.clear()
    user_params = await get_user_parameters(message.from_user.id)
    if not user_params:
        await message.answer("Пользователь не найден в базе данных.")
        return

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=f"Изменить прибыль (Текущая: {user_params.profit})", callback_data="change_profit")],
            [InlineKeyboardButton(text=f"Изменить падение (Текущее: {user_params.loss})", callback_data="change_loss")],
            [InlineKeyboardButton(text=f"Изменить паузу (Текущая: {user_params.pause})", callback_data="change_pause")],
            [InlineKeyboardButton(text=f"Изменить сумму покупки (Текущая: {user_params.buy_amount})", callback_data="change_buy_amount")],
        ]
    )
    await message.answer("Выберите параметр для изменения:", reply_markup=keyboard)


@router.callback_query(F.data == "change_profit")
async def change_profit(callback_query: CallbackQuery, state: FSMContext):
    logger.info(f"User {callback_query.from_user.id} selected to change profit")
    await callback_query.message.answer("Введите новую прибыль (например, 5.5):")
    await state.set_state(ParameterChange.waiting_for_profit)
    await callback_query.answer()


@router.callback_query(F.data == "change_pause")
async def change_pause(callback_query: CallbackQuery, state: FSMContext):
    logger.info(f"User {callback_query.from_user.id} selected to change pause")
    await callback_query.message.answer("Введите новую паузу (целое число):")
    await state.set_state(ParameterChange.waiting_for_pause)
    await callback_query.answer()


@router.callback_query(F.data == "change_loss")
async def change_loss(callback_query: CallbackQuery, state: FSMContext):
    logger.info(f"User {callback_query.from_user.id} selected to change loss")
    await callback_query.message.answer("Введите новое падение (например, 3.5):")
    await state.set_state(ParameterChange.waiting_for_loss)
    await callback_query.answer()
    
@router.callback_query(F.data == "change_buy_amount")
async def change_buy_amount(callback_query: CallbackQuery, state: FSMContext):
    logger.info(f"User {callback_query.from_user.id} selected to change buy amount")
    await callback_query.message.answer("Введите новую сумму покупки (например, 100):")
    await state.set_state(ParameterChange.waiting_for_buy_amount)
    await callback_query.answer()


# Обработчики изменения параметров
@router.message(ParameterChange.waiting_for_profit)
async def set_profit(message: Message, state: FSMContext):
    logger.info(f"User {message.from_user.id} is setting profit with value {message.text}")
    try:
        profit = float(message.text)
        await save_user_parameter(message.from_user.id, 'profit', profit)
        await message.answer(f"[OK] Прибыль успешно изменена на: {profit}")
    except ValueError:
        await message.answer("❌ Некорректное значение. Попробуйте снова.")
    finally:
        await state.clear()


@router.message(ParameterChange.waiting_for_pause)
async def set_pause(message: Message, state: FSMContext):
    logger.info(f"User {message.from_user.id} is setting pause with value {message.text}")
    try:
        pause = int(message.text)
        await save_user_parameter(message.from_user.id, 'pause', pause)
        await message.answer(f"[OK] Пауза успешно изменена на: {pause}")
    except ValueError:
        await message.answer("❌ Некорректное значение. Попробуйте снова.")
    finally:
        await state.clear()


@router.message(ParameterChange.waiting_for_loss)
async def set_loss(message: Message, state: FSMContext):
    logger.info(f"User {message.from_user.id} is setting loss with value {message.text}")
    try:
        loss = float(message.text)
        await save_user_parameter(message.from_user.id, 'loss', loss)
        await message.answer(f"[OK] Падение успешно изменено на: {loss}")
    except ValueError:
        await message.answer("❌ Некорректное значение. Попробуйте снова.")
    finally:
        await state.clear()


@router.message(ParameterChange.waiting_for_buy_amount)
async def set_buy_amount(message: Message, state: FSMContext):
    logger.info(f"User {message.from_user.id} is setting buy amount with value {message.text}")
    try:
        buy_amount = float(message.text)
        await save_user_parameter(message.from_user.id, 'buy_amount', buy_amount)
        await message.answer(f"[OK] Сумма покупки успешно изменена на: {buy_amount}")
    except ValueError:
        await message.answer("❌ Некорректное значение. Попробуйте снова.")
    finally:
        await state.clear()


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
