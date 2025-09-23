import asyncio
import time
from typing import Dict, List

from asgiref.sync import sync_to_async
from bot.logger import logger
from users.models import User, Deal
from bot.utils.mexc import get_user_client, get_actual_order_status


async def _reconcile_user_orders(user: User) -> None:
    """Reconcile one user's active orders against REST API and update DB."""
    try:
        # Skip if no pair configured
        if not user.pair:
            return

        # Collect active deals from DB
        active_deals: List[Deal] = await sync_to_async(list)(
            Deal.objects.filter(user=user, status__in=["NEW", "PARTIALLY_FILLED"]).order_by("-created_at")
        )
        if not active_deals:
            return

        # Fetch open orders from REST for the configured pair
        try:
            client, symbol = get_user_client(user.telegram_id)
        except Exception as e:
            logger.warning(f"[Reconciler] Failed to get client for user {user.telegram_id}: {e}")
            return

        try:
            # Offload blocking SDK call to thread to avoid event loop starvation, with timeout
            open_orders = await asyncio.wait_for(asyncio.to_thread(client.open_orders, symbol=symbol), timeout=20)
        except Exception as e:
            logger.warning(f"[Reconciler] open_orders failed for user {user.telegram_id}: {e}")
            open_orders = []

        # Map and update
        deals_by_id: Dict[str, Deal] = {d.order_id: d for d in active_deals}
        api_by_id: Dict[str, Dict] = {str(o.get("orderId")): o for o in open_orders if o.get("orderId")}

        # First, update deals that are present in open_orders
        for order_id, order in api_by_id.items():
            if order_id in deals_by_id:
                deal = deals_by_id[order_id]
                current_status = order.get("status")
                if current_status and current_status != deal.status:
                    deal.status = current_status
                    await sync_to_async(deal.save)()

        # Then, for DB-active deals that are missing in open_orders, confirm status via query_order
        for order_id, deal in deals_by_id.items():
            if order_id not in api_by_id:
                try:
                    api_status = await sync_to_async(get_actual_order_status)(user, deal.symbol, deal.order_id)
                    if api_status and api_status != deal.status:
                        deal.status = api_status
                        await sync_to_async(deal.save)()
                except Exception as e:
                    logger.warning(f"[Reconciler] query_order failed for {order_id} (user {user.telegram_id}): {e}")

    except Exception as e:
        logger.error(f"[Reconciler] Unexpected error for user {getattr(user, 'telegram_id', 'unknown')}: {e}")


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
                User.objects.exclude(api_key__isnull=True).exclude(api_key='').exclude(api_secret__isnull=True).exclude(api_secret='')
            )
            for user in users:
                await _reconcile_user_orders(user)
        except Exception as e:
            logger.error(f"[Reconciler] Top-level loop error: {e}")

        # Sleep remaining time of the interval if processing was fast
        elapsed = time.time() - start_ts
        sleep_for = max(5, poll_interval_seconds - int(elapsed))
        await asyncio.sleep(sleep_for)





