from aiogram import Router

from bot.commands.base import router as base_router  # Команда /start
from bot.commands.set_keys import router as set_keys_router  # Команда /set_keys
from bot.commands.faq import router as faq_router  # Команда /faq
from bot.commands.subscription import router as subscription_router  # Команда /subscription
from bot.commands.pair import router as pair_router  # Команда /pair

def setup_routers() -> Router:
    router = Router()
    router.include_router(base_router)
    router.include_router(set_keys_router)
    router.include_router(faq_router)
    router.include_router(subscription_router)
    router.include_router(pair_router)
    return router
