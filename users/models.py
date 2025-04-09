from django.db import models


class User(models.Model):
    name = models.CharField(max_length=255, null=True, blank=True)
    telegram_id = models.BigIntegerField(unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return str(self.telegram_id)

    class Meta:
        verbose_name = 'Пользователь telegram'
        verbose_name_plural = 'Пользователи telegram'
