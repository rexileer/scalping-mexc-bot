from django.db import models


class BotMessageForStart(models.Model):
    text = models.TextField()
    image = models.FileField(upload_to='media/', blank=True, null=True)
    
    def save(self, *args, **kwargs):
        if BotMessageForStart.objects.exists():
            # Разрешаем обновлять только первую запись
            self.pk = BotMessageForStart.objects.first().pk
        super().save(*args, **kwargs)
        
    def __str__(self):
        return "Сообщение пользователю по команде start"
    
    class Meta:
        verbose_name = 'Сообщение пользователю по команде start'
        verbose_name_plural = 'Сообщение пользователю по команде start'
    
class BotMessagesForKeys(models.Model):
    access_key = models.TextField()
    secret_key = models.TextField()
    access_image = models.FileField(upload_to='media/', blank=True, null=True)
    secret_image = models.FileField(upload_to='media/', blank=True, null=True)
    
    def save(self, *args, **kwargs):
        if BotMessageForStart.objects.exists():
            # Разрешаем обновлять только первую запись
            self.pk = BotMessageForStart.objects.first().pk
        super().save(*args, **kwargs)
        
    def __str__(self):
        return "Сообщение пользователю по команде set_keys"
    
    class Meta:
        verbose_name = 'Сообщение пользователю по команде set_keys'
        verbose_name_plural = 'Сообщение пользователю по команде set_keys'
    
class BotMessageForSubscription(models.Model):
    text = models.TextField()
    image = models.FileField(upload_to='media/', blank=True, null=True)
    
    def save(self, *args, **kwargs):
        if BotMessageForSubscription.objects.exists():
            # Разрешаем обновлять только первую запись
            self.pk = BotMessageForSubscription.objects.first().pk
        super().save(*args, **kwargs)
        
    def __str__(self):
        return "Сообщение пользователям для оформления подписки"
    
    class Meta:
        verbose_name = 'Сообщение пользователю для оформления подписки'
        verbose_name_plural = 'Сообщение пользователю для оформления подписки'