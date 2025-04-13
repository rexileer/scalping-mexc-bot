from django.contrib import admin
from users.models import User, Deal


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ('telegram_id', 'name', 'created_at', 'api_key', 'api_secret', 'pair', 'is_active')
    
@admin.register(Deal)
class DealAdmin(admin.ModelAdmin):
    list_display = ('user', 'order_id', 'symbol', 'quantity', 'buy_price', 'sell_price', 'status', 'created_at', 'updated_at')