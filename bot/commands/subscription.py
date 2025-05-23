from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.filters import Command
from subscriptions.models import Subscription
from editing.models import BotMessageForSubscription
from django.utils.timezone import now
from bot.constants import DEFAULT_PAYMENT_MESSAGE
from aiogram.types import FSInputFile
from logger import logger
from bot.utils.bot_logging import log_command, log_callback

router = Router()

@router.message(Command("subscription"))
async def subscription(message: Message):
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name or str(user_id)
    command = "/subscription"
    response_text = ""
    success = True
    extra_data = {"username": username, "chat_id": message.chat.id}
    
    try:
        # Ищем подписку для пользователя
        try:
            subscription = await Subscription.objects.filter(
                user__telegram_id=message.from_user.id,
                expires_at__gte=now()
            ).afirst()
        except Subscription.DoesNotExist:
            response_text = "У вас нет активной подписки. Пожалуйста, оформите подписку для получения доступа."
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

        if subscription:
            # Вычисляем оставшееся время до окончания подписки
            remaining_time = subscription.expires_at - now()
            extra_data["subscription_id"] = subscription.id
            extra_data["expires_at"] = subscription.expires_at.isoformat()
            
            if remaining_time.total_seconds() <= 0:
                response_text = "Ваша подписка истекла. Пожалуйста, оформите новую подписку."
                # Показываем кнопку для оплаты
                payment_button = InlineKeyboardButton("Получить платежное сообщение", callback_data="subscribe_payment")
                keyboard = InlineKeyboardMarkup(inline_keyboard=[[payment_button]])
                await message.answer(response_text, reply_markup=keyboard)
            else:
                # Форматируем оставшееся время
                remaining_days = remaining_time.days
                remaining_hours = remaining_time.seconds // 3600
                remaining_minutes = (remaining_time.seconds % 3600) // 60
                
                extra_data["remaining_days"] = remaining_days
                extra_data["remaining_hours"] = remaining_hours
                extra_data["remaining_minutes"] = remaining_minutes

                response_text = (
                    f"Ваша подписка активна.\n"
                    f"Осталось: {remaining_days} дней, {remaining_hours} часов и {remaining_minutes} минут."
                )

                payment_button = InlineKeyboardButton(text="Продлить подписку", callback_data="subscription_payment")
                keyboard = InlineKeyboardMarkup(inline_keyboard=[[payment_button]])
                await message.answer(response_text, reply_markup=keyboard)
        else:
            response_text = "У вас нет активной подписки. Пожалуйста, оформите подписку для получения доступа."
            await message.answer(response_text)
            
            # Добавляем информацию в extra_data
            extra_data["has_subscription"] = False
    except Exception as e:
        logger.exception(f"Ошибка при проверке подписки для {user_id}")
        response_text = f"Ошибка при получении информации о подписке: {str(e)}"
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

@router.callback_query(F.data == "subscription_payment")
async def handle_payment_button(callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    username = callback_query.from_user.username or callback_query.from_user.first_name or str(user_id)
    callback_data = callback_query.data
    response_text = ""
    success = True
    extra_data = {
        "username": username,
        "chat_id": callback_query.message.chat.id if callback_query.message else None,
        "callback_data": callback_data
    }
    
    try:
        # Получаем сообщение для подписки
        try:
            bot_message = await BotMessageForSubscription.objects.afirst()  # Сохраняем только первую запись
            extra_data["has_custom_message"] = bot_message is not None
            extra_data["has_image"] = bot_message and bot_message.image is not None
        except Exception as e:
            logger.error(f"Ошибка при получении сообщения для подписки: {e}")
            response_text = DEFAULT_PAYMENT_MESSAGE
            await callback_query.message.edit_text(response_text, parse_mode="HTML")
            
            # Логируем callback и ответ
            await log_callback(
                user_id=user_id,
                callback_data=callback_data,
                response=response_text,
                success=False,
                extra_data=extra_data
            )
            return

        # Отправляем платежное сообщение
        if bot_message and bot_message.image:
            # Если есть изображение, отправляем его
            await callback_query.message.delete()
            file = FSInputFile(bot_message.image.path)
            response_text = bot_message.text
            await callback_query.message.answer_photo(file, response_text, parse_mode="HTML")
        else:
            response_text = bot_message.text if bot_message else DEFAULT_PAYMENT_MESSAGE
            await callback_query.message.edit_text(response_text, parse_mode="HTML")

        # Подтверждаем обработку callback'а
        await callback_query.answer()
    except Exception as e:
        logger.exception(f"Ошибка при обработке платежного callback для {user_id}")
        response_text = "Ошибка при обработке запроса на оплату."
        success = False
        await callback_query.answer(response_text, show_alert=True)
    
    # Логируем callback и ответ
    await log_callback(
        user_id=user_id,
        callback_data=callback_data,
        response=response_text,
        success=success,
        extra_data=extra_data
    )

