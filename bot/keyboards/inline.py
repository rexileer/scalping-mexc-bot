from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from faq.models import FAQ
from bot.constants import MONTHS_RU

def get_period_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📅 Сегодня", callback_data="stats:today")],
        [InlineKeyboardButton(text="📅 Последние 7 дней", callback_data="stats:7d")],
        [InlineKeyboardButton(text="📆 Выбрать месяц", callback_data="stats:select_month")],
        [InlineKeyboardButton(text="📆 Выбрать год", callback_data="stats:select_year")],
        [InlineKeyboardButton(text="🕰 Всё время", callback_data="stats:all")],
    ])


def get_year_keyboard(current_year):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=str(current_year), callback_data=f"stats:year:{current_year}")],
        [InlineKeyboardButton(text=str(current_year - 1), callback_data=f"stats:year:{current_year - 1}")],
        [InlineKeyboardButton(text="↩ Назад", callback_data="stats:back")],
    ])
    
def get_year_for_month_keyboard(current_year):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=str(current_year), callback_data=f"stats:yeartomonth:{current_year}")],
        [InlineKeyboardButton(text=str(current_year - 1), callback_data=f"stats:yeartomonth:{current_year - 1}")],
        [InlineKeyboardButton(text="↩ Назад", callback_data="stats:back")],
    ])

def get_month_keyboard(year):
    buttons = []
    for i in range(1, 13, 2):
        row = [
            InlineKeyboardButton(text=MONTHS_RU[i], callback_data=f"stats:month:{year}:{i}"),
            InlineKeyboardButton(text=MONTHS_RU[i+1], callback_data=f"stats:month:{year}:{i+1}")
        ]
        buttons.append(row)

    buttons.append([
        InlineKeyboardButton(text="↩ Назад", callback_data="stats:select_year")
    ])

    return InlineKeyboardMarkup(inline_keyboard=buttons)

    
def get_faq_keyboard():
    faqs = FAQ.objects.all()
    inline_buttons = [
        [InlineKeyboardButton(text=faq.question[:20], callback_data=f'faq_{faq.id}')]
        for faq in faqs
    ]
    return InlineKeyboardMarkup(inline_keyboard=inline_buttons)

# Общая клавиатура параметров
def build_parameters_keyboard(user_params):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=f"Изменить прибыль (Текущая: {user_params.profit})", callback_data="change_profit")],
            [InlineKeyboardButton(text=f"Изменить падение (Текущее: {user_params.loss})", callback_data="change_loss")],
            [InlineKeyboardButton(text=f"Изменить паузу (Текущая: {user_params.pause})", callback_data="change_pause")],
            [InlineKeyboardButton(text=f"Изменить сумму покупки (Текущая: {user_params.buy_amount})", callback_data="change_buy_amount")],
        ]
    )
