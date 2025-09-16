import json
import asyncio
import time
from typing import Dict, Any, Optional
from decimal import Decimal

from logger import logger

from users.models import User, Deal
from asgiref.sync import sync_to_async
from bot.utils.bot_utils import send_message_safely

# Импортируем функцию из autobuy.py
from bot.commands.autobuy import process_order_update_for_autobuy


async def handle_order_update(user_id: int, data: Dict[str, Any]):
    """
    Process order update events from user websocket stream.

    Args:
        user_id: The Telegram ID of the user
        data: The WebSocket message data
    """
    try:
        # Decode and process order update
        if not isinstance(data, dict):
            logger.error(f"Invalid order update data format: {data}")
            return

        # Extract order details
        event_type = data.get('e')

        if event_type == 'executionReport':
            order_id = data.get('i')
            symbol = data.get('s')
            status = data.get('X')
            price = data.get('p')
            executed_qty = data.get('z')

            logger.info(f"Order update for user {user_id}: {symbol} - {status} - {price} - {executed_qty}")

            # Update order in database
            await update_order_status(order_id, symbol, status)

            # TODO: Implement any additional logic for order status changes
            # For example, sending notifications to the user
    except Exception as e:
        logger.exception(f"Error handling order update for user {user_id}: {e}")


async def update_order_status(order_id: str, symbol: str, status: str, user_id: Optional[int] = None):
    """Update order status in the database and notify user if needed.

    If user_id is provided, the deal will be resolved within that user's scope.
    """
    try:
        @sync_to_async
        def get_and_update_deal():
            try:
                if user_id is not None:
                    deal = Deal.objects.get(order_id=order_id, user__telegram_id=user_id)
                else:
                    deal = Deal.objects.get(order_id=order_id)
                old_status = deal.status
                # Обновляем только если статус изменился
                if old_status != status:
                    deal.status = status
                    deal.save()
                    logger.info(f"Updated deal status: {deal.order_id} - {old_status} -> {status}")
                    return deal, old_status != status, deal.user.telegram_id
                return deal, False, deal.user.telegram_id
            except Deal.DoesNotExist:
                logger.warning(f"Deal with order_id {order_id} not found (user={user_id})")
                return None, False, None
            except Exception as e:
                logger.error(f"Error updating deal: {e}")
                return None, False, None

        deal, status_changed, deal_user_id = await get_and_update_deal()
        effective_user_id = user_id or deal_user_id

        # Если сделка найдена, передаем информацию в автобай (независимо от смены статуса)
        if deal and effective_user_id:
            await handle_autobuy_order_update(order_id, symbol, status, effective_user_id)

        # Если статус изменился и сделка найдена, отправляем уведомление
        if status_changed and deal:
            user = await sync_to_async(lambda: deal.user)()

            if status == "FILLED":
                # Рассчитываем прибыль
                buy_total = deal.quantity * deal.buy_price
                sell_total = deal.quantity * deal.sell_price
                profit = sell_total - buy_total
                base = symbol[:3]
                quote = symbol[3:]

                text = (
                    f"✅ *СДЕЛКА {deal.user_order_number} ЗАВЕРШЕНА*\n\n"
                    f"📦 Кол-во: `{deal.quantity:.6f}` {base}\n"
                    f"💰 Продано по: `{deal.sell_price:.6f}` {quote}\n"
                    f"📊 Прибыль: `{profit:.4f}` {quote}"
                )

                await send_message_safely(user.telegram_id, text, parse_mode='Markdown')

            elif status == "CANCELED":
                text = (
                    f"❌ *СДЕЛКА {deal.user_order_number} ОТМЕНЕНА*\n\n"
                    f"📦 Кол-во: `{deal.quantity:.6f}` {symbol[:3]}\n"
                    f"💰 Куплено по: `{deal.buy_price:.6f}` {symbol[3:]}\n"
                    f"📈 Продажа: `{deal.quantity:.4f}` {symbol[:3]} по {deal.sell_price:.6f} {symbol[3:]}\n"
                )

                await send_message_safely(user.telegram_id, text, parse_mode='Markdown')

    except Exception as e:
        logger.exception(f"Error in update_order_status: {e}")


async def handle_price_update(symbol: str, price: str) -> None:
    """
    Process price updates from market data stream.
    This is a placeholder function that can be expanded later.

    Args:
        symbol: Trading pair symbol
        price: Current price
    """
    try:
        # For now just log the price update
        logger.debug(f"Price update: {symbol} - {price}")

        # In the future you might want to:
        # 1. Update cached prices
        # 2. Check for price alerts
        # 3. Trigger automated trading logic based on price movements
    except Exception as e:
        logger.exception(f"Error handling price update: {e}")


async def handle_bookticker_update(symbol: str, bid_price: str, ask_price: str, bid_qty: str, ask_qty: str) -> None:
    """
    Process bookTicker updates from market data stream.
    
    Args:
        symbol: Trading pair symbol
        bid_price: Best bid price
        ask_price: Best ask price  
        bid_qty: Quantity at best bid
        ask_qty: Quantity at best ask
    """
    try:
        # Calculate spread
        try:
            bid = float(bid_price)
            ask = float(ask_price)
            spread = ask - bid
            spread_percentage = (spread / bid) * 100 if bid > 0 else 0
            
            # Логируем только раз в 10 секунд для уменьшения спама
            current_time = time.time()
            if not hasattr(handle_bookticker_update, 'last_log_time'):
                handle_bookticker_update.last_log_time = {}
            
            if symbol not in handle_bookticker_update.last_log_time or \
               current_time - handle_bookticker_update.last_log_time.get(symbol, 0) > 10:
                
                # logger.debug(f"BookTicker update: {symbol} - bid: {bid_price} ({bid_qty}), ask: {ask_price} ({ask_qty})")
                # logger.debug(f"BookTicker spread for {symbol}: {spread:.8f} ({spread_percentage:.4f}%)")
                handle_bookticker_update.last_log_time[symbol] = current_time
                
        except (ValueError, TypeError):
            logger.warning(f"Could not calculate spread for {symbol}: bid={bid_price}, ask={ask_price}")

        # Future enhancements could include:
        # 1. Store bookTicker data in database/cache
        # 2. Trigger spread-based trading strategies
        # 3. Send alerts for unusual spreads
        # 4. Update autobuy logic with more precise entry/exit points
        # 5. Arbitrage opportunity detection
        
    except Exception as e:
        logger.exception(f"Error handling bookTicker update for {symbol}: {e}")


async def handle_account_update(user_id: int, data: Dict[str, Any]):
    """
    Process account update events from user websocket stream.

    Args:
        user_id: The Telegram ID of the user
        data: The WebSocket message data
    """
    try:
        # Decode and process account update
        if not isinstance(data, dict):
            logger.error(f"Invalid account update data format: {data}")
            return

        event_type = data.get('e')

        if event_type == 'outboundAccountPosition':
            balances = data.get('B', [])
            logger.info(f"Account update for user {user_id}: {len(balances)} balances updated")

            # TODO: Implement any logic for account balance changes
            # For example, triggering alerts when balance changes significantly
    except Exception as e:
        logger.exception(f"Error handling account update for user {user_id}: {e}")


async def handle_autobuy_order_update(order_id: str, symbol: str, status: str, user_id: int):
    """Специальный обработчик для ордеров автобая"""
    try:
        # Получаем сделку
        deal = await sync_to_async(lambda: Deal.objects.filter(order_id=order_id, is_autobuy=True).first())()

        if deal:
            # Вызываем обработчик для обновления состояния автобая
            await process_order_update_for_autobuy(order_id, symbol, status, user_id)
    except Exception as e:
        logger.exception(f"Error in handle_autobuy_order_update: {e}")
