import asyncio
from aiogram import Bot
from datetime import timedelta
from django.utils import timezone
import pytz
from users.models import User, Deal
from subscriptions.models import Subscription
from bot.logger import logger
from asgiref.sync import sync_to_async

MOSCOW_TZ = pytz.timezone("Europe/Moscow")
DAILY_STATS_TIME = "00:00"  # Moscow time

async def scheduler(bot: Bot):
    """Main scheduler function that runs multiple scheduled tasks"""
    logger.info("Starting scheduler")
    
    while True:
        now = timezone.now()
        
        # Вычисляем время следующего запуска
        moscow_now = now.astimezone(MOSCOW_TZ)
        next_stats_run = moscow_now.replace(
            hour=int(DAILY_STATS_TIME.split(':')[0]),
            minute=int(DAILY_STATS_TIME.split(':')[1]),
            second=0,
            microsecond=0
        )
        if next_stats_run <= moscow_now:
            next_stats_run += timedelta(days=1)
        next_stats_run_utc = next_stats_run.astimezone(pytz.UTC)
        
        # Вычисляем время следующего запуска для проверки истекающих подписок каждые 6 часов
        hours_since_epoch = now.timestamp() // 3600
        next_sub_check_hours = (hours_since_epoch // 6 + 1) * 6
        next_sub_check = timezone.datetime.fromtimestamp(
            next_sub_check_hours * 3600, tz=pytz.UTC
        )
        
        # Определяем время следующего запуска
        next_run_time = min(next_stats_run_utc, next_sub_check)
        wait_seconds = max((next_run_time - now).total_seconds(), 0)
        
        task_name = "daily stats" if next_run_time == next_stats_run_utc else "subscription checks"
        logger.info(f"Next scheduled task: {task_name} in {wait_seconds:.2f} seconds")
        
        # Ждем до следующего запуска
        await asyncio.sleep(wait_seconds)
        
        # Запускаем задачу
        if next_run_time == next_stats_run_utc:
            logger.info("Running daily statistics task")
            await process_and_send_stats(bot)
        else:
            logger.info("Running subscription expiration checks")
            await check_subscription_expiration(bot)

@sync_to_async
def get_all_users():
    """Get all users from the database"""
    return list(User.objects.all())

@sync_to_async
def get_user_deals(user, start_date, end_date):
    """Get all completed deals for a user within the date range"""
    return list(Deal.objects.filter(
        user=user,
        created_at__range=(start_date, end_date),
        status="FILLED"
    ))

@sync_to_async
def get_expiring_subscriptions():
    """Get users whose subscriptions expire tomorrow"""
    tomorrow = timezone.now().date() + timedelta(days=1)
    tomorrow_start = timezone.make_aware(
        timezone.datetime.combine(tomorrow, timezone.datetime.min.time())
    )
    tomorrow_end = timezone.make_aware(
        timezone.datetime.combine(tomorrow, timezone.datetime.max.time())
    )
    
    return list(Subscription.objects.filter(
        expires_at__range=(tomorrow_start, tomorrow_end)
    ).select_related('user'))

async def process_and_send_stats(bot: Bot):
    """Process and send daily statistics to all users"""
    # Вычисляем даты
    moscow_now = timezone.now().astimezone(MOSCOW_TZ)
    yesterday_msk = moscow_now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=1)
    today_msk = moscow_now.replace(hour=0, minute=0, second=0, microsecond=0)
    
    # Переводим в UTC
    yesterday = yesterday_msk.astimezone(pytz.UTC)
    today = today_msk.astimezone(pytz.UTC)
    
    logger.info(f"Processing daily stats for range: {yesterday} — {today} (UTC)")
    
    # Получаем всех пользователей
    users = await get_all_users()
    
    for user in users:
        # Получаем сделки
        deals = await get_user_deals(user, yesterday, today)
        
        if not deals:
            logger.info(f"No deals for user {user.telegram_id} on {yesterday_msk.date()} (Moscow)")
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
        
        avg_profit_percent = percent_total / len(deals)
        period_label = yesterday_msk.strftime('%d.%m.%Y')
        
        stats_message = (
            f"📊 <b>Статистика за {period_label}</b>\n\n"
            f"🔄 Количество сделок: {len(deals)}\n"
            f"💰 Прибыль: {profit_total:.2f} {user.pair[3:]}\n"
            f"📈 Средний % профита: {avg_profit_percent:.2f}%"
        )
        
        try:
            msg = await bot.send_message(user.telegram_id, stats_message, parse_mode="HTML")
            await bot.pin_chat_message(user.telegram_id, msg.message_id, disable_notification=True)
            logger.info(f"Daily stats sent and pinned to {user.telegram_id}")
        except Exception as e:
            logger.error(f"Failed to send statistics to user {user.telegram_id}: {e}")

async def check_subscription_expiration(bot: Bot):
    """Check and notify users whose subscription expires tomorrow or in 36 hours"""
    tomorrow = timezone.now() + timedelta(days=1)
    hours_36_later = timezone.now() + timedelta(hours=36)
    
    # Получаем пользователей, чьи подписки заканчиваются завтра
    expiring_subscriptions = await sync_to_async(list)(
        Subscription.objects.filter(
            expires_at__lte=hours_36_later
        ).select_related('user')
    )
    
    for subscription in expiring_subscriptions:
        user = subscription.user
        hours_remaining = max(int((subscription.expires_at - timezone.now()).total_seconds() / 3600), 0)
        
        # Пропускаем пользователей, чьи подписки заканчиваются в ближайшее время
        if hours_remaining > 36 or hours_remaining < 1:
            continue
            
        warning_message = (
            f"❗ *Подписка на бота закончится через {hours_remaining} часов* ❗\n\n"
            f"*Для продления доступа на 30 дней*\n\n"
            f"*1)* Оплатите *100 USDT* в сети *TRC20 (tron)* на кошелек\n"
            f"`TCh1xdkncgoSELQwa35EC6hTAcwnu3E5XP` (нажмите для копирования).\n"
            f"_При оплате учитывайте комиссию._\n\n"
            f"*2)* Пришлите скрин оплаты с хэшем (TXID) из истории транзакций Вашего кошелька в ЛС @ScalpingBotSupport.\n\n"
            f"_Обратите внимание!_\n"
            f"В случае неоплаты доступ к боту будет автоматически закрыт и все Ваши данные будут удалены. При этом открытые ордера на бирже останутся."
        )
        
        try:
            await bot.send_message(user.telegram_id, warning_message, parse_mode="Markdown")
            logger.info(f"Subscription expiration warning sent to {user.telegram_id}, {hours_remaining} hours remaining")
        except Exception as e:
            logger.error(f"Failed to send subscription warning to user {user.telegram_id}: {e}")

def start_scheduler(bot: Bot):
    """Start the scheduler as a background task"""
    asyncio.create_task(scheduler(bot))
