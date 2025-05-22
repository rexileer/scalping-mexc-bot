import os
import logging
from django.core.management.base import BaseCommand
from django.db import connection
from django.utils import timezone
from datetime import timedelta

from logs.config import LogConfig

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Настройка регулярной очистки логов с помощью PostgreSQL cron'

    def add_arguments(self, parser):
        parser.add_argument(
            '--days',
            type=int,
            default=LogConfig.RETENTION_DAYS,
            help=f'Количество дней, после которых логи удаляются (по умолчанию: {LogConfig.RETENTION_DAYS})'
        )
        parser.add_argument(
            '--disable',
            action='store_true',
            help='Отключить автоматическую очистку логов'
        )

    def handle(self, *args, **options):
        # Проверка, что используется PostgreSQL
        if connection.vendor != 'postgresql':
            self.stdout.write(
                self.style.ERROR('Эта команда работает только с PostgreSQL')
            )
            return

        days = options['days']
        disable = options['disable']

        # SQL для проверки наличия расширения pg_cron
        check_extension_sql = "SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_cron');"
        
        with connection.cursor() as cursor:
            cursor.execute(check_extension_sql)
            has_pg_cron = cursor.fetchone()[0]
            
            if not has_pg_cron:
                self.stdout.write(
                    self.style.ERROR('Расширение pg_cron не установлено в PostgreSQL. '
                                    'Установите его или используйте другой метод очистки логов.')
                )
                return
            
            # Удаляем существующее задание, если оно есть
            cursor.execute("SELECT cron.unschedule('cleanup_logs_job');")
            
            if disable:
                self.stdout.write(
                    self.style.SUCCESS('Автоматическая очистка логов отключена')
                )
                return
                
            # SQL запрос для создания регулярного задания очистки
            # Каждый день в 3:00 ночи удаляем записи старше указанного количества дней
            create_job_sql = f"""
            SELECT cron.schedule(
                'cleanup_logs_job',
                '0 3 * * *',
                $$DELETE FROM logs_botlog WHERE timestamp < NOW() - INTERVAL '{days} days'$$
            );
            """
            
            cursor.execute(create_job_sql)
            
            self.stdout.write(
                self.style.SUCCESS(f'Регулярная очистка логов настроена. '
                                  f'Логи старше {days} дней будут автоматически удаляться каждый день в 3:00.')
            )
            
            # Логируем настройку
            logger.info(f'Настроена автоматическая очистка логов. '
                       f'Логи старше {days} дней будут удаляться ежедневно.') 