from django.contrib import admin
from users.models import User, Deal


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ('telegram_id', 'name', 'created_at', 'api_key', 'api_secret', 'pair', 'autobuy', 'buy_amount', 'profit', 'pause', 'loss')
    
@admin.register(Deal)
class DealAdmin(admin.ModelAdmin):
    list_display = ('user', 'user_order_number', 'order_id', 'symbol', 'quantity', 'buy_price', 'sell_price', 'status', 'created_at', 'updated_at', 'is_autobuy')