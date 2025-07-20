from aiogram import Router

from bot.commands.base import router as base_router  # Команда /start
from bot.commands.set_keys import router as set_keys_router  # Команда /set_keys
from bot.commands.faq import router as faq_router  # Команда /faq
from bot.commands.subscription import router as subscription_router  # Команда /subscription
from bot.commands.parameters import router as parameters_router  # Команда /parameters
from bot.commands.trading import router as trading_router # Команды /price, /buy, /auto_buy, /balance, /status, /stats
from bot.commands.stats import router as stats_router  # stats
from bot.commands.bookticker_demo import router as bookticker_demo_router  # bookticker_demo
from bot.commands.websocket_debug import router as websocket_debug_router  # debug commands
from bot.commands.trigger_debug import router as trigger_debug_router  # trigger debug commands
from bot.commands.trigger_demo import router as trigger_demo_router  # trigger demo commands
from bot.commands.drop_test import router as drop_test_router  # drop test commands
from bot.commands.bookticker_check import router as bookticker_check_router  # bookticker check commands

def setup_routers() -> Router:
    router = Router()
    router.include_router(base_router)
    router.include_router(set_keys_router)
    router.include_router(faq_router)
    router.include_router(subscription_router)
    router.include_router(parameters_router)
    
    router.include_router(trading_router)
    router.include_router(stats_router)
    
    router.include_router(bookticker_demo_router)
    router.include_router(websocket_debug_router)
    router.include_router(trigger_debug_router)
    router.include_router(trigger_demo_router)
    router.include_router(drop_test_router)
    router.include_router(bookticker_check_router)
    return router
