from django.contrib import admin
from .models import BotMessageForStart, BotMessagesForKeys, BotMessageForSubscription


@admin.register(BotMessageForStart)
class BotMessageForStartAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return not BotMessageForStart.objects.exists()  # Разрешаем добавлять, только если нет записей


@admin.register(BotMessagesForKeys)
class BotMessagesForKeysAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return not BotMessagesForKeys.objects.exists()  # Разрешаем добавлять, только если нет записей
    
@admin.register(BotMessageForSubscription)
class BotMessageForSubscriptionAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return not BotMessageForSubscription.objects.exists()  # Разрешаем добавлять, только если нет записей
