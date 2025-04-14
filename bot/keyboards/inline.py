from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from faq.models import FAQ

def get_period_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📅 Сегодня", callback_data="stats:today")],
        [InlineKeyboardButton(text="📆 Последние 7 дней", callback_data="stats:7d")],
        [InlineKeyboardButton(text="📊 Этот месяц", callback_data="stats:month")],
        [InlineKeyboardButton(text="🕰 Всё время", callback_data="stats:all")],
    ])

def get_pair_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="KAS/USDT", callback_data="pair_KASUSDT")],
        [InlineKeyboardButton(text="BTC/USDC", callback_data="pair_BTCUSDC")],
    ])
    
def get_faq_keyboard():
    faqs = FAQ.objects.all()
    inline_buttons = [
        [InlineKeyboardButton(text=faq.question[:20], callback_data=f'faq_{faq.id}')]
        for faq in faqs
    ]
    return InlineKeyboardMarkup(inline_keyboard=inline_buttons)
