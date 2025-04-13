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
    buy_amount = models.DecimalField(max_digits=10, decimal_places=2, default=10.00)


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
            if self.buy_amount is None:
                self.buy_amount = base_params.buy_amount
            self.save()

class Deal(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    order_id = models.CharField(max_length=64)
    symbol = models.CharField(max_length=20)
    buy_price = models.DecimalField(max_digits=20, decimal_places=8)  # Стоимость покупки
    sell_price = models.DecimalField(max_digits=20, decimal_places=8, null=True, blank=True)  # Стоимость продажи
    quantity = models.DecimalField(max_digits=20, decimal_places=8)
    status = models.CharField(max_length=20, default="NEW")  # NEW, FILLED, PARTIALLY_FILLED, etc.
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Order ID: {self.order_id}, Symbol: {self.symbol}, Buy Price: {self.buy_price}, Sell Price: {self.sell_price}, Quantity: {self.quantity}, Status: {self.status}"
