from django.conf import settings

class Config:
    def __init__(self):
        self.bot_token = settings.TELEGRAM_BOT_TOKEN
        self.pair = settings.PAIR

# Глобальный экземпляр бота
bot_instance = None

def load_config() -> Config:
    return Config()
