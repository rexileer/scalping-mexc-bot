import pytz
from django.utils import timezone
from users.models import Deal
from datetime import timedelta
from aiogram import Router, F
from aiogram.types import CallbackQuery
from asgiref.sync import sync_to_async
from bot.keyboards.inline import get_period_keyboard, get_month_keyboard, get_year_for_month_keyboard, get_year_keyboard
from users.models import User
from bot.logger import logger
from bot.constants import MONTHS_RU
router = Router()

MOSCOW_TZ = pytz.timezone("Europe/Moscow")

@router.callback_query(F.data == "stats:select_year")
async def select_year(callback_query: CallbackQuery):
    now = timezone.now().astimezone(MOSCOW_TZ)
    current_year = now.year
    keyboard = get_year_keyboard(current_year)
    await callback_query.message.edit_text("Выберите год:", reply_markup=keyboard)

@router.callback_query(F.data == "stats:select_month")
async def select_month(callback_query: CallbackQuery):
    now = timezone.now().astimezone(MOSCOW_TZ)
    current_year = now.year
    keyboard = get_year_for_month_keyboard(current_year)
    await callback_query.message.edit_text("Выберите год:", reply_markup=keyboard)

@router.callback_query(F.data == ("stats:back"))
async def select_month(callback_query: CallbackQuery):
    await callback_query.message.edit_text("Выберите период для статистики:", reply_markup=get_period_keyboard())

@router.callback_query(F.data.startswith("stats:yeartomonth:"))
async def select_month(callback_query: CallbackQuery):
    year = int(callback_query.data.split(":")[2])
    keyboard = get_month_keyboard(year)
    await callback_query.message.edit_text(f"Выберите месяц для {year} года:", reply_markup=keyboard)
    

@router.callback_query(
    F.data.startswith("stats:")
)
async def handle_stats_callback(callback_query: CallbackQuery):
    parts = callback_query.data.split(":")
    now = timezone.now().astimezone(MOSCOW_TZ)

    start_date = end_date = None

    period_label = ""

    if parts[1] == "today":
        start_date = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end_date = now
        period_label = f"{start_date.strftime('%d.%m.%Y')}"
    elif parts[1] == "7d":
        start_date = now - timedelta(days=7)
        end_date = now
        period_label = f"{start_date.strftime('%d.%m.%Y')}–{end_date.strftime('%d.%m.%Y')}"
    elif parts[1] == "year":
        year = int(parts[2])
        start_date = timezone.datetime(year, 1, 1, tzinfo=MOSCOW_TZ)
        end_date = start_date + timedelta(days=365)
        period_label = f"{year} год"
    elif parts[1] == "all":
        start_date = timezone.datetime(2020, 1, 1, tzinfo=MOSCOW_TZ)
        end_date = now
        period_label = "Все время"
    elif parts[1] == "month" and len(parts) == 4:
        year = int(parts[2])
        month = int(parts[3])
        start_date = timezone.datetime(year, month, 1, tzinfo=MOSCOW_TZ)
        last_day = (start_date + timedelta(days=32)).replace(day=1) - timedelta(seconds=1)
        end_date = last_day
        period_label = f"{MONTHS_RU[month]} {year}"
    else:
        await callback_query.message.edit_text("Неверный формат периода.", reply_markup=get_period_keyboard())
        return

    try:
        user_id = callback_query.from_user.id
        user, deals = await get_user_and_deals(user_id, start_date, end_date)

        if not deals:
            stats_message = (
                f"<b>{period_label}</b>\n\n"
                f"Количество сделок: 0\n"
            )
        else:
            profit_total = 0
            percent_total = 0

            for deal in deals:
                total_buy = deal.buy_price * deal.quantity
                total_sell = deal.sell_price * deal.quantity
                profit = total_sell - total_buy
                profit_percent = ((deal.sell_price - deal.buy_price) / deal.buy_price) * 100 if deal.buy_price > 0 else 0

                profit_total += profit
                percent_total += profit_percent

            avg_profit_percent = percent_total / len(deals)
            
            pair = user.pair

            stats_message = (
                f"<b>{period_label}</b>\n\n"
                f"Количество сделок: {len(deals)}\n"
                f"Прибыль: {profit_total:.4f} {pair[3:]}\n"
                f"Средний % профита: {avg_profit_percent:.2f}%"
            )

        await callback_query.message.edit_text(
            stats_message,
            reply_markup=get_period_keyboard(),
            parse_mode="HTML"
        )
        logger.info(f"Stats summary sent to user {user.telegram_id}")

    except Exception as e:
        logger.error(f"Ошибка в handle_stats_callback для {user_id}: {e}")
        if "message is not modified" in str(e):
            pass
        else:
            await callback_query.message.edit_text(
                "Произошла ошибка при получении статистики.",
                reply_markup=get_period_keyboard()
            )
            raise



@sync_to_async
def get_user_and_deals(telegram_id, start_date, end_date):
    user = User.objects.get(telegram_id=telegram_id)
    deals = Deal.objects.filter(
        user=user,
        created_at__range=[start_date, end_date],
        sell_price__isnull=False,
        status="FILLED"
    ).order_by('created_at')
    return user, deals
