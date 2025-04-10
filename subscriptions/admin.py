from django.contrib import admin
from .models import Subscription, BotMessageForSubscription

@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = ('telegram_id', 'name', 'expires_at')
    search_fields = ('telegram_id', 'name')

@admin.register(BotMessageForSubscription)
class BotMessageForSubscriptionAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return not BotMessageForSubscription.objects.exists()  # Разрешаем добавлять, только если нет записей
