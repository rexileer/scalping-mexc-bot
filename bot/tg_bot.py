import os
import sys


sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings")
os.environ.update({'DJANGO_ALLOW_ASYNC_UNSAFE': "true"})

import django
django.setup()

import asyncio
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from bot.config import load_config
from bot.logger import logger
from bot.routers import setup_routers
from bot.middlewares.access_middleware import AccessMiddleware

config = load_config()


async def main():
    try:
        bot = Bot(
            token=config.bot_token,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML)
        )
        dp = Dispatcher(storage=MemoryStorage())

        dp.include_router(setup_routers())
        dp.update.middleware(AccessMiddleware())

        logger.info("Bot started")
        await asyncio.gather(
            bot.delete_webhook(drop_pending_updates=True),
            dp.start_polling(bot, skip_updates=False),
        )

    except Exception as e:
        logger.error(f"Error: {e}")
    finally:
        if 'bot' in locals():
            await bot.close()


if __name__ == "__main__":
    asyncio.run(main())