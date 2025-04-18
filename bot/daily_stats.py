import asyncio
from aiogram import Bot
from datetime import timedelta
from django.utils import timezone
import pytz
from users.models import User, Deal
from bot.logger import logger


MOSCOW_TZ = pytz.timezone("Europe/Moscow")

async def send_daily_statistics(bot: Bot):
    while True:
        now = timezone.now().astimezone(MOSCOW_TZ)
        target = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
        # ВРЕМЕННО для теста: запуск через 1 минуту
        # target = now + timedelta(seconds=10)
        wait_seconds = max((target - now).total_seconds(), 0)
        logger.info(f"Started daily statistics scheduler: {wait_seconds} seconds until next run")
        # Wait until the next day at midnight
        await asyncio.sleep(wait_seconds)

        await process_and_send_stats(bot=bot)


async def process_and_send_stats(bot: Bot):
    today = timezone.now().astimezone(MOSCOW_TZ).replace(hour=0, minute=0, second=0, microsecond=0)
    tomorrow = today + timedelta(days=1)

    users = User.objects.all()

    for user in users:
        deals = Deal.objects.filter(
            user=user,
            created_at__range=(today, tomorrow),
            sell_price__isnull=False,
            status="FILLED"
        )

        if not deals.exists():
            continue

        profit_total = 0
        percent_total = 0

        for deal in deals:
            total_buy = deal.buy_price * deal.quantity
            total_sell = deal.sell_price * deal.quantity
            profit = total_sell - total_buy
            profit_percent = ((deal.sell_price - deal.buy_price) / deal.buy_price) * 100 if deal.buy_price > 0 else 0

            profit_total += profit
            percent_total += profit_percent

        avg_profit_percent = percent_total / deals.count()

        period_label = today.strftime('%d.%m.%Y')
        stats_message = (
            f"<b>{period_label}</b>\n\n"
            f"Количество сделок: {deals.count()}\n"
            f"Прибыль: {profit_total:.2f} {user.pair[3:]}\n"
            f"Средний % профита: {avg_profit_percent:.2f}%"
        )

        try:
            msg = await bot.send_message(user.telegram_id, stats_message)
            await bot.pin_chat_message(user.telegram_id, msg.message_id, disable_notification=True)
            logger.info(f"Daily stats sent and pinned to {user.telegram_id}")
        except Exception as e:
            logger.error(f"Не удалось отправить статистику пользователю {user.telegram_id}: {e}")
