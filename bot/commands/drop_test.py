import asyncio
from aiogram import Router
from aiogram.types import Message
from aiogram.filters import Command

from bot.utils.mexc import get_user_client
from bot.utils.websocket_manager import websocket_manager
from bot.commands.autobuy import autobuy_states
from bot.logger import logger

router = Router()


@router.message(Command("drop_test"))
async def test_drop_logic(message: Message):
    """
    Test drop buying logic by showing current prices and calculations.
    """
    try:
        user_id = message.from_user.id
        
        # Get user's trading client and pair
        client, pair = get_user_client(user_id)
        
        if not pair:
            await message.answer("❌ Валютная пара не указана. Установите пару в /parameters")
            return

        # Get current bookTicker data
        bookticker_data = websocket_manager.get_current_bookticker(pair)
        if not bookticker_data:
            await message.answer("❌ Нет данных bookTicker. Проверьте WebSocket соединение.")
            return

        # Get user settings
        from users.models import User
        from asgiref.sync import sync_to_async
        
        user = await sync_to_async(User.objects.get)(telegram_id=user_id)
        loss_threshold = float(user.loss)
        
        # Get current prices
        bid_price = float(bookticker_data['bid_price'])
        ask_price = float(bookticker_data['ask_price'])
        
        # Get last buy price from autobuy state
        last_buy_price = None
        if user_id in autobuy_states:
            last_buy_price = autobuy_states[user_id].get('last_buy_price')
        
        test_info = []
        test_info.append("📉 *Drop Test Results*\n")
        
        # Show current prices
        test_info.append("📊 *Current Prices:*")
        test_info.append(f"   • Bid: {bid_price:.6f}")
        test_info.append(f"   • Ask: {ask_price:.6f}")
        test_info.append(f"   • Spread: {ask_price - bid_price:.6f}")
        
        # Show last buy price
        if last_buy_price:
            test_info.append(f"\n💰 *Last Buy Price:* {last_buy_price:.6f}")
            
            # Calculate drop percentage
            drop_percent = ((last_buy_price - ask_price) / last_buy_price * 100) if last_buy_price > 0 else 0
            
            test_info.append(f"\n📉 *Drop Calculation:*")
            test_info.append(f"   • Drop %: {drop_percent:.2f}%")
            test_info.append(f"   • Threshold: {loss_threshold:.2f}%")
            test_info.append(f"   • Would Buy: {'✅' if drop_percent >= loss_threshold else '❌'}")
            
            if drop_percent >= loss_threshold:
                test_info.append(f"   • Price Difference: {last_buy_price - ask_price:.6f}")
        else:
            test_info.append(f"\n❌ *Last Buy Price:* Не установлена")
            test_info.append(f"   • Нужна первая покупка для тестирования")
        
        # Show user settings
        test_info.append(f"\n⚙️ *User Settings:*")
        test_info.append(f"   • Loss Threshold: {loss_threshold:.2f}%")
        test_info.append(f"   • Pair: {pair}")
        
        await message.answer('\n'.join(test_info), parse_mode='Markdown')
        
    except Exception as e:
        logger.exception(f"Error in drop test command: {e}")
        await message.answer(f"❌ Ошибка тестирования падения: {str(e)}")


@router.message(Command("price_info"))
async def show_price_info(message: Message):
    """
    Show detailed price information for debugging.
    """
    try:
        user_id = message.from_user.id
        
        # Get user's trading client and pair
        client, pair = get_user_client(user_id)
        
        if not pair:
            await message.answer("❌ Валютная пара не указана. Установите пару в /parameters")
            return

        # Get current bookTicker data
        bookticker_data = websocket_manager.get_current_bookticker(pair)
        if not bookticker_data:
            await message.answer("❌ Нет данных bookTicker. Проверьте WebSocket соединение.")
            return

        # Get price direction
        direction_info = websocket_manager.get_price_direction(pair)
        
        price_info = []
        price_info.append("📊 *Price Information*\n")
        
        # Show bookTicker data
        price_info.append("📈 *BookTicker Data:*")
        price_info.append(f"   • Bid Price: {bookticker_data.get('bid_price', 'N/A')}")
        price_info.append(f"   • Ask Price: {bookticker_data.get('ask_price', 'N/A')}")
        price_info.append(f"   • Bid Qty: {bookticker_data.get('bid_qty', 'N/A')}")
        price_info.append(f"   • Ask Qty: {bookticker_data.get('ask_qty', 'N/A')}")
        
        # Show price direction
        price_info.append(f"\n📊 *Price Direction:*")
        price_info.append(f"   • Is Rise: {'✅' if direction_info.get('is_rise', False) else '❌'}")
        price_info.append(f"   • Current Price: {direction_info.get('current_price', 0):.6f}")
        price_info.append(f"   • Last Change: {direction_info.get('last_change_time', 0):.1f}s ago")
        price_info.append(f"   • History Length: {len(direction_info.get('price_history', []))}")
        
        # Show autobuy state
        if user_id in autobuy_states:
            state = autobuy_states[user_id]
            price_info.append(f"\n🤖 *Autobuy State:*")
            price_info.append(f"   • Last Buy Price: {state.get('last_buy_price', 'None')}")
            price_info.append(f"   • Current Price: {state.get('current_price', 'None')}")
            price_info.append(f"   • Active Orders: {len(state.get('active_orders', []))}")
            price_info.append(f"   • Is Rise Trigger: {'✅' if state.get('is_rise_trigger', False) else '❌'}")
            if state.get('trigger_price'):
                price_info.append(f"   • Trigger Price: {state.get('trigger_price', 'None')}")
        
        await message.answer('\n'.join(price_info), parse_mode='Markdown')
        
    except Exception as e:
        logger.exception(f"Error in price info command: {e}")
        await message.answer(f"❌ Ошибка получения информации о ценах: {str(e)}") 