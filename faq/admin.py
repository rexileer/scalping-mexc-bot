from django.contrib import admin
from faq.models import FAQ
from django.utils.html import format_html
from django.forms import FileInput
from django.db import models

@admin.register(FAQ)
class FAQAdmin(admin.ModelAdmin):
    list_display = ("id","question", "media_display")
    readonly_fields = ("media_preview",)

    formfield_overrides = {
        models.FileField: {"widget": FileInput(attrs={"accept": "image/*,video/*"})},
    }

    def media_display(self, obj):
        """Предпросмотр медиа в списке FAQ"""
        if obj.file:
            if obj.media_type == "image":
                return format_html('<img src="{}" style="max-height: 100px; max-width: 150px;" />', obj.file.url)
            elif obj.media_type == "video":
                return format_html('<video width="150" height="100" controls><source src="{}" type="video/mp4"></video>', obj.file.url)
        return "Нет медиа"

    media_display.short_description = "Медиа"

    def media_preview(self, obj):
        """Предпросмотр медиа в форме редактирования"""
        if obj.file:
            if obj.media_type == "image":
                return format_html('<img src="{}" style="max-width: 300px; max-height: 300px; margin-top: 10px;" />', obj.file.url)
            elif obj.media_type == "video":
                return format_html('<video width="300" height="200" controls style="margin-top: 10px;"><source src="{}" type="video/mp4"></video>', obj.file.url)
        return "Нет медиафайла"

    media_preview.short_description = "Предпросмотр медиа"