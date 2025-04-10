from aiogram import Bot
from aiogram.types import BotCommand

async def set_default_commands(bot: Bot):
    commands = [
        BotCommand(command="/start", description="Запустить бота"),
        BotCommand(command="/menu", description="Главное меню"),
        BotCommand(command="/auth", description="Авторизоваться в MEXC"),
        BotCommand(command="/balance", description="Показать баланс"),
        BotCommand(command="/settings", description="Настройки"),
    ]
    await bot.set_my_commands(commands)
