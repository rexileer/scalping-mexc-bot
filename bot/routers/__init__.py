from aiogram import Router

from bot.commands.base import router as base_router  # Команда /start
from bot.commands.set_keys import router as set_keys_router  # Команда /set_keys
from bot.commands.faq import router as faq_router  # Команда /faq
from bot.commands.subscription import router as subscription_router  # Команда /subscription
from bot.commands.parameters import router as parameters_router  # Команда /parameters
from bot.commands.trading import router as trading_router # Команды /price, /buy, /auto_buy, /balance, /status, /stats
from bot.commands.stats import router as stats_router  # stats
from bot.commands.fallback_handler import router as fallback_router  # Обработчик необработанных сообщений и команд

def setup_routers() -> Router:
    router = Router()
    router.include_router(base_router)
    router.include_router(set_keys_router)
    router.include_router(faq_router)
    router.include_router(subscription_router)
    router.include_router(parameters_router)
    
    router.include_router(trading_router)
    router.include_router(stats_router)
    
    # В самом конце подключаем fallback обработчик для всех остальных сообщений
    # Он должен быть последним, чтобы не перехватывать сообщения других обработчиков
    router.include_router(fallback_router)
    
    return router
