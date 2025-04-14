from django.contrib import admin
from .models import Subscription, BotMessageForSubscription

from django import forms
from .models import Subscription
from users.models import User

class SubscriptionForm(forms.ModelForm):
    class Meta:
        model = Subscription
        fields = '__all__'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Только пользователи без подписки
        self.fields['user'].queryset = User.objects.filter(subscription__isnull=True)

@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    form = SubscriptionForm
    list_display = ('user', 'get_telegram_id', 'expires_at')
    search_fields = ('user__telegram_id', 'user__name')

    def get_telegram_id(self, obj):
        return obj.user.telegram_id
    get_telegram_id.short_description = 'Telegram ID'

@admin.register(BotMessageForSubscription)
class BotMessageForSubscriptionAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return not BotMessageForSubscription.objects.exists()  # Разрешаем добавлять, только если нет записей
