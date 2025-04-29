from aiogram.types import BotCommand
from aiogram import Bot

async def set_default_commands(bot: Bot):
    commands = [
        BotCommand(command="/autobuy", description="Автопокупка"),
        BotCommand(command="/buy", description="Покупка"),
        BotCommand(command="/status", description="Статус"),
        BotCommand(command="/stats", description="Статистика"),
        BotCommand(command="/parameters", description="Параметры"),
        BotCommand(command="/balance", description="Баланс"),
        BotCommand(command="/price", description="Цена"),
        BotCommand(command="/subscription", description="Подписка"),
        BotCommand(command="/stop", description="Стоп"),
        BotCommand(command="/faq", description="FAQ"),
        # BotCommand(command="/set_keys", description="Авторизация MEXC/Установка ключей"),
    ]
    await bot.set_my_commands(commands)
