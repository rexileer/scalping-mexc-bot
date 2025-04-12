from django.db import models

class FAQ(models.Model):
    question = models.TextField("Вопрос", blank=True, null=True)
    answer = models.TextField("Ответ", blank=True, null=True)
    file = models.FileField("Медиафайл", upload_to="media/", blank=True, null=True)
    media_type = models.CharField(
        "Тип медиафайла",
        max_length=10,
        choices=[("image", "Изображение"), ("video", "Видео")],
        blank=True,
        null=True,
    )

    def __str__(self):
        return self.question[:50] if self.question else f"FAQ: {self.id}"

    class Meta:
        verbose_name = 'Вопрос-ответ'
        verbose_name_plural = 'Вопросы-ответы'
