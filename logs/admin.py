from django.contrib import admin
from django.utils.html import format_html
from .models import BotLog, LogLevel

@admin.register(BotLog)
class BotLogAdmin(admin.ModelAdmin):
    list_display = ('colored_level', 'timestamp', 'user_display', 'message_short', 'has_extra_data')
    list_filter = ('level', 'timestamp', 'user')
    search_fields = ('message', 'user__name', 'user__telegram_id')
    readonly_fields = ('timestamp', 'level', 'user', 'message', 'extra_data_pretty')
    date_hierarchy = 'timestamp'
    
    def colored_level(self, obj):
        colors = {
            LogLevel.DEBUG: '#6c757d',   # Серый
            LogLevel.INFO: '#17a2b8',    # Синий
            LogLevel.WARNING: '#ffc107', # Желтый
            LogLevel.ERROR: '#dc3545',   # Красный
        }
        color = colors.get(obj.level, '#6c757d')
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            color, obj.level
        )
    colored_level.short_description = 'Уровень'
    
    def user_display(self, obj):
        if obj.user:
            return obj.user.name or f"ID: {obj.user.telegram_id}"
        return "—"
    user_display.short_description = 'Пользователь'
    
    def message_short(self, obj):
        return obj.message[:100] + ('...' if len(obj.message) > 100 else '')
    message_short.short_description = 'Сообщение'
    
    def has_extra_data(self, obj):
        return bool(obj.extra_data)
    has_extra_data.boolean = True
    has_extra_data.short_description = 'Доп. данные'
    
    def extra_data_pretty(self, obj):
        if not obj.extra_data:
            return "—"
        
        import json
        from django.utils.safestring import mark_safe
        
        formatted = json.dumps(obj.extra_data, indent=2, ensure_ascii=False)
        return mark_safe(f'<pre>{formatted}</pre>')
    extra_data_pretty.short_description = 'Дополнительные данные (форматированные)'
    
    def has_add_permission(self, request):
        return False
    
    def has_change_permission(self, request, obj=None):
        return False
