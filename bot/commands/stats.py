from users.models import Deal
from datetime import datetime, timedelta, timezone
from aiogram import Router, F
from aiogram.types import CallbackQuery
from asgiref.sync import sync_to_async

from users.models import User
from bot.logger import logger

router = Router()

UTC_OFFSET = timedelta(hours=3)  # UTC+3


@router.callback_query(F.data.startswith("stats:"))
async def handle_stats_callback(callback_query: CallbackQuery):
    data = callback_query.data.split(":")[1]
    now = datetime.utcnow() + UTC_OFFSET  # используем UTC + 3

    if data == "today":
        start_date = now.replace(hour=0, minute=0, second=0, microsecond=0)
    elif data == "7d":
        start_date = now - timedelta(days=7)
    elif data == "month":
        start_date = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    elif data == "all":
        start_date = datetime(2020, 1, 1, tzinfo=timezone.utc)

    end_date = now
    await callback_query.message.answer("Формирую статистику...")

    try:
        user_id = callback_query.from_user.id
        user, deals = await get_user_and_deals(user_id, start_date, end_date)

        stats_message = f"📈 Статистика (с {start_date.strftime('%d.%m.%Y')} по {end_date.strftime('%d.%m.%Y')}):\n"

        if not deals:
            stats_message += "\nНет завершённых продаж за указанный период."
            await callback_query.message.answer(stats_message)
            return

        profit_total = 0
        percent_total = 0

        for deal in deals:
            buy_price = deal.buy_price
            sell_price = deal.sell_price
            amount = deal.quantity

            total_buy = buy_price * amount
            total_sell = sell_price * amount
            profit = total_sell - total_buy
            profit_percent = ((sell_price - buy_price) / buy_price) * 100 if buy_price > 0 else 0

            profit_total += profit
            percent_total += profit_percent

            autobuy = "(AutoBuy)" if deal.is_autobuy else ""
            stats_message += (
                f"\n🧾 <b>{deal.order_id}</b> {autobuy}\n"
                f"{amount:.4f} {deal.symbol[:3]}\n"
                f"🔹 Куплено по: {buy_price:.5f} ({total_buy:.2f} {deal.symbol[3:]})\n"
                f"🔸 Продано по: {sell_price:.5f} ({total_sell:.2f} {deal.symbol[3:]})\n"
                f"📊 Прибыль: {profit:.2f} {deal.symbol[3:]} ({profit_percent:.2f}%)\n"
                f"🕒 {(deal.created_at + UTC_OFFSET).strftime('%d.%m.%Y %H:%M:%S')}\n"
            )

        avg_profit_percent = percent_total / len(deals)

        stats_message += (
            f"\n━━━━━━━━━━━━━━━\n"
            f"💰 <b>Общая прибыль</b>: {profit_total:.2f} USDT/USDC\n"
            f"📈 <b>Средний % профита</b>: {avg_profit_percent:.2f}%"
        )

        await callback_query.message.answer(stats_message)
        logger.info(f"Stats sent to user {user.telegram_id}")

    except Exception as e:
        logger.error(f"Ошибка в send_stats для {user_id}: {e}")
        await callback_query.message.answer("Произошла ошибка при получении статистики.")


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
