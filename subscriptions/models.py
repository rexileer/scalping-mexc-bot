from django.db import models

class Subscription(models.Model):
    telegram_id = models.BigIntegerField(unique=True)
    name = models.CharField(max_length=255, blank=True, null=True)
    expires_at = models.DateTimeField()

    def __str__(self):
        return f"{self.telegram_id} — до {self.expires_at}"
