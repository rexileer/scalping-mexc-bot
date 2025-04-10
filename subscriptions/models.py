from django.db import models

class Subscription(models.Model):
    telegram_id = models.BigIntegerField(unique=True)
    name = models.CharField(max_length=255, blank=True, null=True)
    expires_at = models.DateTimeField()

    def __str__(self):
        return f"{self.telegram_id} — до {self.expires_at}"
    
    class Meta:
        verbose_name = 'Подписка'
        verbose_name_plural = 'Подписки'

class BotMessageForSubscription(models.Model):
    text = models.TextField()
    
    def save(self, *args, **kwargs):
        if BotMessageForSubscription.objects.exists():
            # Разрешаем обновлять только первую запись
            self.pk = BotMessageForSubscription.objects.first().pk
        super().save(*args, **kwargs)
        
    def __str__(self):
        return "Сообщение пользователям для оформления подписки"