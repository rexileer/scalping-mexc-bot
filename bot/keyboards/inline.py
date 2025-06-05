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

# Клавиатура пагинации для функции status
def get_pagination_keyboard(current_page, total_pages, user_id):
    """
    Создает клавиатуру пагинации для просмотра ордеров
    
    Args:
        current_page (int): Текущая страница
        total_pages (int): Всего страниц
        user_id (int): ID пользователя (для идентификации в callback_data)
        
    Returns:
        InlineKeyboardMarkup: Клавиатура с кнопками "<", "текущая/всего", ">"
    """
    buttons = []
    
    # Создаем ряд с тремя кнопками
    row = []
    
    # Кнопка "назад" (неактивна на первой странице)
    prev_button = InlineKeyboardButton(
        text="◀️",
        callback_data=f"status_page:{user_id}:{current_page-1}" if current_page > 1 else "dummy_callback"
    )
    row.append(prev_button)
    
    # Кнопка с информацией о текущей странице
    page_info = InlineKeyboardButton(
        text=f"{current_page}/{total_pages}",
        callback_data="dummy_callback"  # Эта кнопка не должна вызывать действие
    )
    row.append(page_info)
    
    # Кнопка "вперед" (неактивна на последней странице)
    next_button = InlineKeyboardButton(
        text="▶️",
        callback_data=f"status_page:{user_id}:{current_page+1}" if current_page < total_pages else "dummy_callback"
    )
    row.append(next_button)
    
    buttons.append(row)
    
    return InlineKeyboardMarkup(inline_keyboard=buttons)
