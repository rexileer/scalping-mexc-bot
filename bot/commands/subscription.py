from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.filters import Command
from subscriptions.models import Subscription
from editing.models import BotMessageForSubscription
from django.utils.timezone import now
from bot.constants import DEFAULT_PAYMENT_MESSAGE

router = Router()

@router.message(Command("subscription"))
async def subscription(message: Message):
    # Ищем подписку для пользователя
    try:
        subscription = await Subscription.objects.filter(
            user__telegram_id=message.from_user.id,
            expires_at__gte=now()
        ).afirst()
    except Subscription.DoesNotExist:
        await message.answer("У вас нет активной подписки. Пожалуйста, оформите подписку для получения доступа.")
        return

    # Вычисляем оставшееся время до окончания подписки
    remaining_time = subscription.expires_at - now()
    if remaining_time.total_seconds() <= 0:
        await message.answer("Ваша подписка истекла. Пожалуйста, оформите новую подписку.")
        # Показываем кнопку для оплаты
        payment_button = InlineKeyboardButton("Получить платежное сообщение", callback_data="subscribe_payment")
        keyboard = InlineKeyboardMarkup(inline_keyboard=[[payment_button]])
        await message.answer("Ваша подписка истекла.", reply_markup=keyboard)
        return

    # Форматируем оставшееся время
    remaining_days = remaining_time.days
    remaining_hours = remaining_time.seconds // 3600
    remaining_minutes = (remaining_time.seconds % 3600) // 60

    response = (
        f"Ваша подписка активна.\n"
        f"Осталось: {remaining_days} дней, {remaining_hours} часов и {remaining_minutes} минут."
    )

    payment_button = InlineKeyboardButton(text="Продлить подписку", callback_data="subscription_payment")
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[payment_button]])
    await message.answer(response, reply_markup=keyboard)

@router.callback_query(F.data == "subscription_payment")
async def handle_payment_button(callback_query: CallbackQuery):
    # Получаем сообщение для подписки
    try:
        bot_message = BotMessageForSubscription.objects.first()  # Сохраняем только первую запись
    except:
        await callback_query.edit_text(DEFAULT_PAYMENT_MESSAGE, parse_mode="HTML")
        return

    # Отправляем платежное сообщение
    await callback_query.message.edit_text(bot_message.text, parse_mode="HTML")

    # Подтверждаем обработку callback'а
    await callback_query.answer()

