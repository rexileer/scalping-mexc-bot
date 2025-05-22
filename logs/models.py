from django.db import models
import json
from django.utils import timezone
from datetime import timedelta

class LogLevel(models.TextChoices):
    DEBUG = 'DEBUG', 'Debug'
    INFO = 'INFO', 'Info'
    WARNING = 'WARNING', 'Warning'
    ERROR = 'ERROR', 'Error'

class BotLog(models.Model):
    timestamp = models.DateTimeField(auto_now_add=True, verbose_name='Время')
    level = models.CharField(
        max_length=10,
        choices=LogLevel.choices,
        default=LogLevel.INFO,
        verbose_name='Уровень'
    )
    user = models.ForeignKey(
        'users.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name='Пользователь'
    )
    message = models.TextField(verbose_name='Сообщение')
    extra_data = models.JSONField(null=True, blank=True, verbose_name='Дополнительные данные')

    class Meta:
        verbose_name = 'Лог'
        verbose_name_plural = 'Логи'
        ordering = ['-timestamp']

    def __str__(self):
        return f"{self.timestamp} [{self.level}] - {self.message[:50]}"

    @classmethod
    def cleanup_old_logs(cls, days=7):
        """Удаляет логи старше заданного количества дней"""
        cutoff_date = timezone.now() - timedelta(days=days)
        return cls.objects.filter(timestamp__lt=cutoff_date).delete()
