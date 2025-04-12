from django.db import models


class User(models.Model):
    name = models.CharField(max_length=255, null=True, blank=True)
    telegram_id = models.BigIntegerField(unique=True)
    api_key = models.CharField(max_length=255, unique=True, null=True, blank=True)
    api_secret = models.CharField(max_length=255, unique=True, null=True, blank=True)
    pair = models.CharField(
        "Торговая пара",
        max_length=30,
        choices=[
            ("KAS_USDT", "KAS/USDT"),
            ("BTC_USDC", "BTC/USDC"),
        ],
        blank=True,
        null=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    profit = models.FloatField(null=True, blank=True)
    pause = models.IntegerField(null=True, blank=True)
    loss = models.FloatField(null=True, blank=True)
    is_active = models.BooleanField(default=False) 


    def __str__(self):
        return str(self.telegram_id)

    class Meta:
        verbose_name = 'Пользователь telegram'
        verbose_name_plural = 'Пользователи telegram'
