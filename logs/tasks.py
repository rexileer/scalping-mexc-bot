import asyncio
import logging
from django.core.management.base import BaseCommand
from logs.services import cleanup_old_logs_async
from logs.config import LogConfig

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Очистка старых логов'

    def handle(self, *args, **options):
        if not LogConfig.AUTO_CLEANUP_ENABLED:
            self.stdout.write('Автоматическая очистка логов отключена в настройках')
            return

        loop = asyncio.get_event_loop()
        deleted_count = loop.run_until_complete(
            cleanup_old_logs_async(days=LogConfig.RETENTION_DAYS)
        )
        
        self.stdout.write(
            self.style.SUCCESS(f'Успешно удалено {deleted_count} логов старше {LogConfig.RETENTION_DAYS} дней')
        )
        logger.info(f'Очистка логов: удалено {deleted_count} записей')


# Для запуска через cron или планировщик задач Django
# Например, добавить в CRONJOBS в settings.py:
# CRONJOBS = [
#     ('0 0 * * *', 'logs.tasks.Command().handle')  # Каждый день в полночь
# ] 