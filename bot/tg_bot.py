import os
import sys
import traceback


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
from bot.daily_stats import start_scheduler
from bot.config import load_config
from bot.logger import logger, log_to_db
from bot.routers import setup_routers
from bot.middlewares.access_middleware import AccessMiddleware
from bot.middlewares.auth_middleware import AuthMiddleware
from bot.middlewares.logging_middleware import LoggingMiddleware
from bot.utils.set_commands import set_default_commands

config = load_config()


async def main():
    try:
        logger.info("Starting bot initialization...")
        bot = Bot(
            token=config.bot_token,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML)
        )
        dp = Dispatcher(storage=MemoryStorage())

        # Подключаем все маршрутизаторы
        dp.include_router(setup_routers())
        
        # Подключаем middleware
        dp.message.middleware(AccessMiddleware())
        dp.message.middleware(AuthMiddleware())
        
        # Добавляем middleware для логирования всех сообщений и команд
        dp.message.middleware(LoggingMiddleware())
        dp.callback_query.middleware(LoggingMiddleware())
        
        # Запускаем планировщик задач
        start_scheduler(bot)
        
        # Устанавливаем команды бота
        await set_default_commands(bot)
        logger.info("Bot started successfully")
        
        # Добавляем запись в БД о запуске бота
        await log_to_db("Бот запущен", level='INFO', extra_data={
            'type': 'bot_start',
            'version': '1.0',
            'environment': os.environ.get('DJANGO_SETTINGS_MODULE', 'unknown')
        })
        
        # Запускаем бота
        logger.info("Starting polling...")
        await asyncio.gather(
            bot.delete_webhook(drop_pending_updates=True),
            dp.start_polling(bot, skip_updates=False),
        )

    except Exception as e:
        error_traceback = traceback.format_exc()
        logger.error(f"Error while starting bot: {e}\n{error_traceback}")
        # Логируем ошибку в БД
        try:
            await log_to_db(
                f"Ошибка при запуске бота: {e}", 
                level='ERROR', 
                extra_data={
                    'type': 'bot_error',
                    'traceback': error_traceback,
                }
            )
        except Exception as log_error:
            # Если логирование в БД тоже не работает, выводим в консоль
            logger.critical(f"Failed to log error to database: {log_error}")
    finally:
        if 'bot' in locals():
            try:
                # Логируем остановку бота
                await log_to_db("Бот остановлен", level='INFO', extra_data={
                    'type': 'bot_stop',
                })
                await bot.close()
            except Exception as close_error:
                logger.error(f"Error while closing bot: {close_error}")


if __name__ == "__main__":
    # Обрабатываем Ctrl+C и другие сигналы завершения
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by keyboard interrupt")
    except Exception as e:
        logger.critical(f"Unhandled exception: {e}\n{traceback.format_exc()}")
        sys.exit(1)