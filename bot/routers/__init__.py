from aiogram import Router

# from bot.commands.autobuy import router as autobuy_router
# from bot.commands.balance import router as balance_router
# from bot.commands.buy import router as buy_router
# from bot.commands.help import router as help_router
# from bot.commands.parameters import router as parameters_router
# from bot.commands.price import router as price_router
# from bot.commands.stats import router as stats_router
# from bot.commands.status import router as status_router
# from bot.commands.stop import router as stop_router
# from bot.commands.subscription import router as subscription_router
from bot.commands.base import router as base_router  # Команды типа /start

def setup_routers() -> Router:
    router = Router()
    router.include_router(base_router)
    # router.include_router(help_router)
    # router.include_router(balance_router)
    # router.include_router(price_router)
    # router.include_router(buy_router)
    # router.include_router(stop_router)
    # router.include_router(stats_router)
    # router.include_router(subscription_router)
    # router.include_router(autobuy_router)
    # router.include_router(parameters_router)
    # router.include_router(status_router)
    return router
