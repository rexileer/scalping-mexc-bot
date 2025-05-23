from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from asgiref.sync import sync_to_async
from .states import ParameterChange
from users.models import User
from bot.logger import logger
from bot.keyboards.inline import build_parameters_keyboard
from bot.utils.bot_logging import log_command, log_callback

router = Router()


# Команда для отображения параметров
@router.message(F.text == "/parameters")
async def show_parameters(message: Message, state: FSMContext):
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name or str(user_id)
    command = "/parameters"
    response_text = "Выберите параметр для изменения:"
    success = True
    extra_data = {"username": username, "chat_id": message.chat.id}
    
    try:
        await state.clear()
        user_params = await get_user_parameters(message.from_user.id)
        
        if not user_params:
            response_text = "Пользователь не найден в базе данных."
            success = False
            await message.answer(response_text)
            
            # Логируем команду и ответ
            await log_command(
                user_id=user_id,
                command=command,
                response=response_text,
                success=success,
                extra_data=extra_data
            )
            return

        # Добавляем текущие параметры в extra_data
        extra_data["profit"] = float(user_params.profit)
        extra_data["loss"] = float(user_params.loss)
        extra_data["pause"] = int(user_params.pause)
        extra_data["buy_amount"] = float(user_params.buy_amount)
        
        keyboard = build_parameters_keyboard(user_params)
        sent = await message.answer(response_text, reply_markup=keyboard)
        await state.update_data(menu_message_id=sent.message_id)
    except Exception as e:
        logger.exception(f"Ошибка при отображении параметров для {user_id}")
        response_text = f"Ошибка при получении параметров: {str(e)}"
        success = False
        await message.answer(response_text)
    
    # Логируем команду и ответ
    await log_command(
        user_id=user_id,
        command=command,
        response=response_text,
        success=success,
        extra_data=extra_data
    )


async def handle_param_change(callback_query: CallbackQuery, state: FSMContext, text: str, state_to_set):
    user_id = callback_query.from_user.id
    username = callback_query.from_user.username or callback_query.from_user.first_name or str(user_id)
    callback_data = callback_query.data
    response_text = text
    success = True
    extra_data = {
        "username": username, 
        "chat_id": callback_query.message.chat.id,
        "parameter": callback_data.replace("change_", "")
    }
    
    try:
        await callback_query.message.edit_text(text)
        await state.set_state(state_to_set)
        await state.update_data(menu_message_id=callback_query.message.message_id)
        await callback_query.answer()
    except Exception as e:
        logger.exception(f"Ошибка при обработке изменения параметра {callback_data} для {user_id}")
        response_text = f"Ошибка при изменении параметра: {str(e)}"
        success = False
        await callback_query.answer("Произошла ошибка")
    
    # Логируем callback
    await log_callback(
        user_id=user_id,
        callback_data=callback_data,
        response=response_text,
        success=success,
        extra_data=extra_data
    )


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
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name or str(user_id)
    command = f"set_{field}"
    response_text = ""
    success = True
    extra_data = {
        "username": username, 
        "chat_id": message.chat.id,
        "parameter": field,
        "value_text": message.text
    }
    
    try:
        value = parser(message.text)
        extra_data["value"] = value
        
        await save_user_parameter(message.from_user.id, field, value)
        user_params = await get_user_parameters(message.from_user.id)
        keyboard = build_parameters_keyboard(user_params)
        data = await state.get_data()
        menu_message_id = data.get("menu_message_id")

        # Формируем текст ответа
        response_text = f"✅ Параметр `{field}` обновлён: `{value}`\n\nВыберите следующий параметр:"
        
        # Редактируем старое сообщение бота с новой клавиатурой
        await message.bot.edit_message_text(
            chat_id=message.chat.id,
            message_id=menu_message_id,
            text=response_text,
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
    except ValueError as e:
        response_text = "❌ Некорректное значение. Попробуйте снова."
        success = False
        await message.answer(response_text)
        extra_data["error"] = str(e)
    except Exception as e:
        logger.exception(f"Ошибка при сохранении параметра {field} для {user_id}")
        response_text = f"Ошибка при сохранении параметра: {str(e)}"
        success = False
        await message.answer(response_text)
        extra_data["error"] = str(e)
    finally:
        await message.delete()  # Удаляем сообщение пользователя
        await state.clear()
    
    # Логируем изменение параметра
    await log_command(
        user_id=user_id,
        command=command,
        response=response_text,
        success=success,
        extra_data=extra_data
    )


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
