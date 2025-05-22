import asyncio
import logging
from django.core.management.base import BaseCommand
from logs.services import cleanup_old_logs_async
from logs.config import LogConfig

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Очистка старых логов'

    def add_arguments(self, parser):
        parser.add_argument(
            '--days',
            type=int,
            default=LogConfig.RETENTION_DAYS,
            help=f'Количество дней, после которых логи удаляются (по умолчанию: {LogConfig.RETENTION_DAYS})'
        )
        parser.add_argument(
            '--force',
            action='store_true',
            help='Принудительно выполнить очистку даже если автоматическая очистка отключена'
        )

    def handle(self, *args, **options):
        days = options['days']
        force = options['force']
        
        if not LogConfig.AUTO_CLEANUP_ENABLED and not force:
            self.stdout.write(
                self.style.WARNING('Автоматическая очистка логов отключена в настройках. '
                                   'Используйте --force для принудительной очистки.')
            )
            return

        loop = asyncio.get_event_loop()
        deleted_count = loop.run_until_complete(
            cleanup_old_logs_async(days=days)
        )
        
        self.stdout.write(
            self.style.SUCCESS(f'Успешно удалено {deleted_count} логов старше {days} дней')
        )
        logger.info(f'Очистка логов: удалено {deleted_count} записей') 