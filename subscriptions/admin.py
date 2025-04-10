from django.contrib import admin
from .models import Subscription

@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = ('telegram_id', 'name', 'expires_at')
    search_fields = ('telegram_id', 'name')
