from django.contrib import admin
from parameters.models import BaseParameters
from django.utils.translation import gettext_lazy as _

@admin.register(BaseParameters)
class BaseParametersAdmin(admin.ModelAdmin):
    list_display = ('profit', 'pause', 'loss', 'buy_amount')
    def has_add_permission(self, request):
        return not BaseParameters.objects.exists()  # Разрешаем добавлять, только если нет записей

    def has_delete_permission(self, request, obj=None):
        return False  # Запрещаем удаление