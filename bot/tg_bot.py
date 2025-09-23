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
from bot import config  # Импортируем модуль config
from bot.logger import logger, log_to_db
from bot.routers import setup_routers
from bot.middlewares.access_middleware import AccessMiddleware
from bot.middlewares.auth_middleware import AuthMiddleware
from bot.middlewares.logging_middleware import LoggingMiddleware
from bot.middlewares.error_reporting_middleware import ErrorReportingMiddleware
from bot.utils.set_commands import set_default_commands
from bot.utils.log_cleaner import start_log_cleaner
from bot.utils.websocket_manager import websocket_manager
from bot.utils.autobuy_restart import restart_autobuy_for_users
from bot.utils.reconciler import order_status_reconciler_loop
from django.conf import settings

config_obj = load_config()


async def main():
    try:
        logger.info("Starting bot initialization...")
        bot = Bot(
            token=config_obj.bot_token,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML)
        )
        # Сохраняем экземпляр бота в глобальную переменную для доступа из других модулей
        config.bot_instance = bot
        
        dp = Dispatcher(storage=MemoryStorage())

        # Подключаем все маршрутизаторы
        dp.include_router(setup_routers())
        
        # Подключаем middleware (ошибки первыми, чтобы перехватывать как можно больше)
        dp.message.middleware(ErrorReportingMiddleware())
        dp.callback_query.middleware(ErrorReportingMiddleware())
        dp.message.middleware(AccessMiddleware())
        dp.message.middleware(AuthMiddleware())
        
        # Добавляем middleware для логирования всех сообщений и команд
        dp.message.middleware(LoggingMiddleware())
        dp.callback_query.middleware(LoggingMiddleware())
        
        # Запускаем планировщик задач
        start_scheduler(bot)
        
        # Запускаем очистку логов каждые 30 минут
        retention_days = getattr(settings, 'LOG_RETENTION_DAYS', 7)
        log_cleaner_task = await start_log_cleaner(retention_days=retention_days)
        
        # Устанавливаем команды бота
        await set_default_commands(bot)

        # Тест нотификатора в админ-чат (однократно при старте)
        try:
            from bot.utils.error_notifier import notify_error_text
            await notify_error_text("🧪 Нотификатор активен: бот запущен")
        except Exception:
            pass
        
        # Инициализируем WebSocket соединения для всех пользователей с ключами
        logger.info("Initializing WebSocket connections for users...")
        websocket_init_task = asyncio.create_task(websocket_manager.connect_valid_users())
        
        # Запускаем мониторинг соединений
        connection_monitor_task = asyncio.create_task(websocket_manager.monitor_connections())

        # Фоновый reconciler статусов ордеров
        reconciler_task = asyncio.create_task(order_status_reconciler_loop(poll_interval_seconds=60))
        
        # Инициализируем общее WebSocket соединение для мониторинга цен
        # Будем инициализировать его по требованию
        logger.info("Bot started successfully")
        
        # Добавляем запись в БД о запуске бота
        await log_to_db("Бот запущен", level='INFO', extra_data={
            'type': 'bot_start',
            'version': '1.0',
            'environment': os.environ.get('DJANGO_SETTINGS_MODULE', 'unknown')
        })
        
        # Рестарт autobuy для пользователей с активным статусом
        logger.info("Restarting autobuy for users with active status...")
        autobuy_restart_task = asyncio.create_task(restart_autobuy_for_users(bot))
        
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
                # Закрываем все WebSocket соединения
                logger.info("Closing all WebSocket connections...")
                await websocket_manager.disconnect_all()
                
                # Логируем остановку бота
                await log_to_db("Бот остановлен", level='INFO', extra_data={
                    'type': 'bot_stop',
                })
                await bot.close()
                # Очищаем глобальную переменную
                config.bot_instance = None
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