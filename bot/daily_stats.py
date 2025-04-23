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
SUBSCRIPTION_WARNING_TIME = "22:50"  # Moscow time

async def scheduler(bot: Bot):
    """Main scheduler function that runs multiple scheduled tasks"""
    logger.info("Starting scheduler")
    
    while True:
        # Current time in Moscow timezone
        now = timezone.now().astimezone(MOSCOW_TZ)
        
        # Calculate next daily stats run time (midnight Moscow time)
        next_stats_run = now.replace(
            hour=int(DAILY_STATS_TIME.split(':')[0]),
            minute=int(DAILY_STATS_TIME.split(':')[1]),
            second=0,
            microsecond=0
        )
        if next_stats_run <= now:
            next_stats_run += timedelta(days=1)
            
        # Calculate next subscription warning run time (noon Moscow time)
        next_sub_warning = now.replace(
            hour=int(SUBSCRIPTION_WARNING_TIME.split(':')[0]),
            minute=int(SUBSCRIPTION_WARNING_TIME.split(':')[1]),
            second=0,
            microsecond=0
        )
        if next_sub_warning <= now:
            next_sub_warning += timedelta(days=1)
            
        # Find which task should run next
        next_run = min(next_stats_run, next_sub_warning)
        wait_seconds = max((next_run - now).total_seconds(), 0)
        
        task_name = "daily stats" if next_run == next_stats_run else "subscription warnings"
        logger.info(f"Next scheduled task: {task_name} in {wait_seconds:.2f} seconds")
        
        # Wait until the next task should run
        await asyncio.sleep(wait_seconds)
        
        # Run the appropriate task
        if next_run == next_stats_run:
            logger.info("Running daily statistics task")
            await process_and_send_stats(bot)
        else:
            logger.info("Running subscription warning task")
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
    # Calculate the date range for yesterday (Moscow time)
    moscow_now = timezone.now().astimezone(MOSCOW_TZ)
    yesterday_msk = moscow_now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=1)
    today_msk = moscow_now.replace(hour=0, minute=0, second=0, microsecond=0)
    
    # Convert to UTC for database queries
    yesterday = yesterday_msk.astimezone(pytz.UTC)
    today = today_msk.astimezone(pytz.UTC)
    
    logger.info(f"Processing daily stats for range: {yesterday} — {today} (UTC)")
    
    # Get all users asynchronously
    users = await get_all_users()
    
    for user in users:
        # Get deals for this user asynchronously
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
    """Check and notify users whose subscription expires tomorrow"""
    expiring_subscriptions = await get_expiring_subscriptions()
    
    for subscription in expiring_subscriptions:
        user = subscription.user
        expiration_date = subscription.expires_at.astimezone(MOSCOW_TZ).strftime('%d.%m.%Y')
        
        warning_message = (
            f"⚠️ <b>Предупреждение о подписке</b>\n\n"
            f"Ваша подписка истекает завтра ({expiration_date}).\n"
            f"Для продления подписки и продолжения работы бота, пожалуйста, "
            f"воспользуйтесь командой /subscribe."
        )
        
        try:
            await bot.send_message(user.telegram_id, warning_message, parse_mode="HTML")
            logger.info(f"Subscription expiration warning sent to {user.telegram_id}")
        except Exception as e:
            logger.error(f"Failed to send subscription warning to user {user.telegram_id}: {e}")

# Function to initialize the scheduler when the bot starts
def start_scheduler(bot: Bot):
    """Start the scheduler as a background task"""
    asyncio.create_task(scheduler(bot))
