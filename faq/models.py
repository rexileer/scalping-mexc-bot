from django.db import models


class FAQ(models.Model):
    text = models.TextField("Текст сообщения", blank=True, null=True)
    file = models.FileField("Медиафайл", upload_to="media/", blank=True, null=True)
    media_type = models.CharField(
        "Тип медиафайла",
        max_length=10,
        choices=[("image", "Изображение"), ("video", "Видео")],
        blank=True,
        null=True,
    )

    def __str__(self):
        if self.text:
            return self.text[:50]
        return f"FAQ: {self.id}"

    class Meta:
        verbose_name = 'Вопрос-ответ'
        verbose_name_plural = 'Вопросы-ответы'