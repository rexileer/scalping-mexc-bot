import asyncio
from aiogram import Router
from aiogram.types import Message
from aiogram.filters import Command

from bot.utils.websocket_manager import websocket_manager
from bot.logger import logger

router = Router()


@router.message(Command("bookticker_check"))
async def check_bookticker_data(message: Message):
    """
    Check if bookTicker data is being stored correctly.
    """
    try:
        # Get all stored bookTicker data
        current_data = websocket_manager.current_bookticker
        
        if not current_data:
            await message.answer("❌ Нет сохраненных данных bookTicker")
            return
        
        # Show all symbols with their data
        info = []
        info.append("📊 *BookTicker Data Status*\n")
        
        for symbol, data in current_data.items():
            info.append(f"🔸 *{symbol}:*")
            info.append(f"   • Bid: {data.get('bid_price', 'N/A')}")
            info.append(f"   • Ask: {data.get('ask_price', 'N/A')}")
            info.append(f"   • Bid Qty: {data.get('bid_qty', 'N/A')}")
            info.append(f"   • Ask Qty: {data.get('ask_qty', 'N/A')}")
            info.append(f"   • Timestamp: {data.get('timestamp', 'N/A')}")
            info.append("")
        
        await message.answer('\n'.join(info), parse_mode='Markdown')
        
    except Exception as e:
        logger.exception(f"Error in bookticker check command: {e}")
        await message.answer(f"❌ Ошибка проверки bookTicker: {str(e)}")


@router.message(Command("ws_status"))
async def check_websocket_status(message: Message):
    """
    Check WebSocket connection status and subscriptions.
    """
    try:
        info = []
        info.append("🔗 *WebSocket Status*\n")
        
        # Market connection status
        market_status = "✅ Подключено" if websocket_manager.market_connection else "❌ Отключено"
        info.append(f"📡 Market Connection: {market_status}")
        
        # Subscriptions
        info.append(f"📊 Market Subscriptions: {len(websocket_manager.market_subscriptions)}")
        info.append(f"📈 BookTicker Subscriptions: {len(websocket_manager.bookticker_subscriptions)}")
        
        if websocket_manager.market_subscriptions:
            info.append(f"   • Market: {', '.join(websocket_manager.market_subscriptions)}")
        
        if websocket_manager.bookticker_subscriptions:
            info.append(f"   • BookTicker: {', '.join(websocket_manager.bookticker_subscriptions)}")
        
        # Callbacks
        info.append(f"🔄 Price Callbacks: {len(websocket_manager.price_callbacks)}")
        info.append(f"🔄 BookTicker Callbacks: {len(websocket_manager.bookticker_callbacks)}")
        
        await message.answer('\n'.join(info), parse_mode='Markdown')
        
    except Exception as e:
        logger.exception(f"Error in websocket status command: {e}")
        await message.answer(f"❌ Ошибка проверки WebSocket: {str(e)}") 