from django.db import models
from users.models import User  # Импортируй модель User

class Subscription(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='subscription', verbose_name='Пользователь', null=True, blank=True)
    expires_at = models.DateTimeField()

    def __str__(self):
        return f"{self.user.name or self.user.telegram_id} — до {self.expires_at}"
    
    class Meta:
        verbose_name = 'Подписка'
        verbose_name_plural = 'Подписки'
