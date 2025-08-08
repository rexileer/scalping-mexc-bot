import json
import time
from typing import List

from logger import logger


async def subscribe_market_data(manager, symbols: List[str]) -> bool:
    """Subscribe to market data for specific symbols."""
    if not manager.market_connection:
        logger.error("Market connection not established - cannot subscribe to market data")
        logger.debug(f"Attempted to subscribe to symbols: {symbols}")
        return False

    try:
        ws = manager.market_connection['ws']

        params = [f"spot@public.aggre.deals.v3.api.pb@100ms@{symbol.upper()}" for symbol in symbols]

        subscription_msg = {
            "method": "SUBSCRIPTION",
            "params": params,
            "id": int(time.time() * 1000),
        }

        logger.info(f"[MarketWS] Sending market data subscription request: {subscription_msg}")
        await ws.send_str(json.dumps(subscription_msg))

        manager.market_subscriptions = list(set(manager.market_subscriptions + symbols))
        logger.info(f"Subscribed to market data for: {symbols}")
        return True
    except Exception as e:
        logger.error(f"Error subscribing to market data: {e}")
        return False


async def subscribe_bookticker_data(manager, symbols: List[str]) -> bool:
    """Subscribe to bookTicker data for specific symbols to get best bid/ask prices."""
    if not manager.market_connection:
        logger.error("Market connection not established for bookTicker subscription")
        return False

    try:
        ws = manager.market_connection['ws']

        params = [f"spot@public.aggre.bookTicker.v3.api.pb@100ms@{symbol.upper()}" for symbol in symbols]

        subscription_msg = {
            "method": "SUBSCRIPTION",
            "params": params,
            "id": int(time.time() * 1000),
        }

        logger.info(f"[MarketWS] Sending bookTicker subscription request: {subscription_msg}")
        await ws.send_str(json.dumps(subscription_msg))

        manager.bookticker_subscriptions = list(set(manager.bookticker_subscriptions + symbols))
        logger.info(f"Subscribed to bookTicker data for: {symbols}")
        return True
    except Exception as e:
        logger.error(f"Error subscribing to bookTicker data: {e}")
        return False


async def subscribe_user_orders(manager, user_id: int, symbol: str = None) -> bool:
    """Subscribe to private orders and account updates for a user."""
    if user_id not in manager.user_connections:
        logger.warning(f"Невозможно подписаться: нет соединения для пользователя {user_id}")
        return False

    try:
        ws = manager.user_connections[user_id]['ws']

        params = [
            "spot@private.orders.v3.api.pb",
            "spot@private.account.v3.api.pb",
        ]

        subscription_msg = {
            "method": "SUBSCRIPTION",
            "params": params,
            "id": int(time.time() * 1000),
        }

        await ws.send_str(json.dumps(subscription_msg))
        logger.info(f"Отправлен запрос на подписку для пользователя {user_id}: {params}")

        if 'subscriptions' not in manager.user_connections[user_id]:
            manager.user_connections[user_id]['subscriptions'] = []
        manager.user_connections[user_id]['subscriptions'].extend(params)

        return True
    except Exception as e:
        logger.error(f"Ошибка при подписке на обновления ордеров пользователя {user_id}: {e}")
        return False

