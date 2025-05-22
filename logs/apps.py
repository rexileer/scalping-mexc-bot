from django.apps import AppConfig


class LogsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'logs'
    verbose_name = 'Логирование'
    
    def ready(self):
        # Можно добавить инициализацию при запуске
        pass
