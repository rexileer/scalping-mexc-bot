import json
import asyncio
from typing import Dict, Any, Optional
from decimal import Decimal

from logger import logger
from users.models import User, Deal
from asgiref.sync import sync_to_async


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


async def update_order_status(order_id: str, symbol: str, status: str):
    """Update order status in the database."""
    try:
        # Use sync_to_async to run DB operations in async context
        @sync_to_async
        def update_deal():
            try:
                deal = Deal.objects.get(order_id=order_id)
                deal.status = status
                deal.save()
                logger.info(f"Updated deal status: {deal.order_id} - {status}")
                return deal
            except Deal.DoesNotExist:
                logger.warning(f"Deal with order_id {order_id} not found")
                return None
            except Exception as e:
                logger.error(f"Error updating deal: {e}")
                return None
        
        await update_deal()
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