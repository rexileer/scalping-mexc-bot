from django.db import models
from parameters.models import BaseParameters

class User(models.Model):
    name = models.CharField(max_length=255, null=True, blank=True)
    telegram_id = models.BigIntegerField(unique=True)
    api_key = models.CharField(max_length=255, unique=True, null=True, blank=True)
    api_secret = models.CharField(max_length=255, unique=True, null=True, blank=True)
    pair = models.CharField(max_length=30, null=True, blank=True, verbose_name='Торговая пара')
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

    def set_default_parameters(self):
        base_params = BaseParameters.objects.first()
        if base_params:
            if self.profit is None:
                self.profit = base_params.profit
            if self.pause is None:
                self.pause = base_params.pause
            if self.loss is None:
                self.loss = base_params.loss
            self.save()