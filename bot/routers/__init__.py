from aiogram import Router

from bot.commands.set_keys import router as set_keys_router  # Команда /set_keys
from bot.commands.base import router as base_router  # Команда /start

def setup_routers() -> Router:
    router = Router()
    router.include_router(base_router)
    router.include_router(set_keys_router)
    return router
