from aiogram.types import BotCommand
from aiogram import Bot

async def set_default_commands(bot: Bot):
    commands = [
        BotCommand(command="/balance", description="Баланс"),
        BotCommand(command="/price", description="Прайс"),
        BotCommand(command="/autobuy", description="Автопокупка"),
        BotCommand(command="/stop", description="Остановить автопокупку"),
        BotCommand(command="/buy", description="Покупка"),
        BotCommand(command="/status", description="Статус"),
        BotCommand(command="/parameters", description="Параметры"),
        BotCommand(command="/faq", description="FAQ"),
        BotCommand(command="/pair", description="Торговая пара"),
        BotCommand(command="/subscription", description="Подписка"),
        BotCommand(command="/stats", description="Статистика"),
        BotCommand(command="/set_keys", description="Авторизация MEXC/Установка ключей"),
    ]
    await bot.set_my_commands(commands)
