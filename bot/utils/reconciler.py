import asyncio
import time
from typing import Dict, List

from asgiref.sync import sync_to_async
from bot.logger import logger
from users.models import User, Deal
from bot.utils.mexc_rest import MexcRestClient
from bot.utils.websocket_handlers import update_order_status


async def _reconcile_user_orders(user: User) -> None:
    """Reconcile one user's active orders against REST API and update DB."""
    try:
        # Skip if no pair configured
        if not user.pair:
            return

        # Collect active deals from DB
        active_deals: List[Deal] = await sync_to_async(list)(
            Deal.objects.filter(
                user=user, status__in=["NEW", "PARTIALLY_FILLED"]
            ).order_by("-created_at")
        )
        if not active_deals:
            return

        # Fetch open orders from REST for the configured pair (async client with time sync and recvWindow)
        try:
            client = MexcRestClient(user.api_key, user.api_secret)
            symbol = (user.pair or "").replace("/", "")
            # Primary attempt
            open_orders = await client.open_orders(symbol)
        except Exception as e:
            # Retry once using local timestamp by forcing zero offset (avoid /api/v3/time dependency)
            try:
                setattr(client, "_time_offset_ms", 0)
                setattr(client, "_last_time_sync", time.time())
                open_orders = await client.open_orders(symbol)
            except Exception as e2:
                logger.warning(
                    f"[Reconciler] open_orders failed for user {user.telegram_id}: {e2}"
                )
                # При ошибке не мутируем БД; пусть следующая итерация или WS восстановит состояние
                open_orders = []

        # Map and update
        deals_by_id: Dict[str, Deal] = {d.order_id: d for d in active_deals}
        api_by_id: Dict[str, Dict] = {
            str(o.get("orderId")): o for o in open_orders if o.get("orderId")
        }

        # First, update deals that are present in open_orders (centralized updater with notifications)
        for order_id, order in api_by_id.items():
            if order_id in deals_by_id:
                current_status = order.get("status")
                if current_status:
                    await update_order_status(
                        order_id, symbol, current_status, user_id=user.telegram_id
                    )

        # Then, for DB-active deals that are missing in open_orders, confirm status via query_order (centralized updater)
        for order_id, deal in deals_by_id.items():
            if order_id not in api_by_id:
                try:
                    resp = await client.query_order(symbol, {"orderId": order_id})
                    api_status = resp.get("status")
                    if api_status:
                        await update_order_status(
                            order_id, symbol, api_status, user_id=user.telegram_id
                        )
                except Exception as e:
                    # Проверяем, является ли ошибка "Order does not exist" (-2013)
                    error_str = str(e)
                    if "-2013" in error_str or "Order does not exist" in error_str:
                        # Ордер не существует в MEXC, помечаем как отмененный
                        logger.info(
                            f"[Reconciler] Order {order_id} does not exist in MEXC, marking as CANCELED for user {user.telegram_id}"
                        )
                        await update_order_status(
                            order_id, symbol, "CANCELED", user_id=user.telegram_id
                        )
                        continue  # Переходим к следующему ордеру
                    
                    # Retry once with local timestamp fallback
                    try:
                        setattr(client, "_time_offset_ms", 0)
                        setattr(client, "_last_time_sync", time.time())
                        resp = await client.query_order(symbol, {"orderId": order_id})
                        api_status = resp.get("status")
                        if api_status:
                            await update_order_status(
                                order_id, symbol, api_status, user_id=user.telegram_id
                            )
                    except Exception as e2:
                        # Проверяем, является ли ошибка "Order does not exist" (-2013)
                        error_str2 = str(e2)
                        if "-2013" in error_str2 or "Order does not exist" in error_str2:
                            # Ордер не существует в MEXC, помечаем как отмененный
                            logger.info(
                                f"[Reconciler] Order {order_id} does not exist in MEXC (retry), marking as CANCELED for user {user.telegram_id}"
                            )
                            await update_order_status(
                                order_id, symbol, "CANCELED", user_id=user.telegram_id
                            )
                        else:
                            logger.warning(
                                f"[Reconciler] query_order failed for {order_id} (user {user.telegram_id}): {e2}"
                            )

    except Exception as e:
        logger.error(
            f"[Reconciler] Unexpected error for user {getattr(user, 'telegram_id', 'unknown')}: {e}"
        )


async def order_status_reconciler_loop(poll_interval_seconds: int = 60) -> None:
    """Continuously reconcile order statuses for all users with API keys.

    - Only updates active statuses (NEW, PARTIALLY_FILLED)
    - Uses open_orders to batch, then per-order query as fallback
    """
    logger.info("[Reconciler] Starting background order status reconciler loop")
    while True:
        start_ts = time.time()
        try:
            users = await sync_to_async(list)(
                User.objects.exclude(api_key__isnull=True)
                .exclude(api_key="")
                .exclude(api_secret__isnull=True)
                .exclude(api_secret="")
            )
            for user in users:
                await _reconcile_user_orders(user)
        except Exception as e:
            logger.error(f"[Reconciler] Top-level loop error: {e}")

        # Sleep remaining time of the interval if processing was fast
        elapsed = time.time() - start_ts
        sleep_for = max(5, poll_interval_seconds - int(elapsed))
        await asyncio.sleep(sleep_for)
