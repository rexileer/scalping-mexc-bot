from django.db import models


class BaseParameters(models.Model):
    profit = models.FloatField(default=0.0)
    pause = models.IntegerField(default=0)
    loss = models.FloatField(default=0.0)
    
    def save(self, *args, **kwargs):
        if BaseParameters.objects.exists():
            # Разрешаем обновлять только первую запись
            self.pk = BaseParameters.objects.first().pk
        super().save(*args, **kwargs)
        
    def __str__(self):
        return f"Прибыль: {self.profit}, Пауза: {self.pause}, Падение: {self.loss}"
    
    class Meta:
        verbose_name = 'Параметры'
        verbose_name_plural = 'Параметры'
    