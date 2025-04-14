from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

def get_period_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📅 Сегодня", callback_data="stats:today")],
        [InlineKeyboardButton(text="📆 Последние 7 дней", callback_data="stats:7d")],
        [InlineKeyboardButton(text="📊 Этот месяц", callback_data="stats:month")],
        [InlineKeyboardButton(text="🕰 Всё время", callback_data="stats:all")],
    ])
