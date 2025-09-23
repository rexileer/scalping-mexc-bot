import asyncio
from aiogram import Router
from aiogram.types import Message
from aiogram.filters import Command

from bot.utils.mexc import get_user_client
from bot.utils.websocket_manager import websocket_manager
from bot.logger import logger

router = Router()


@router.message(Command("trigger_demo"))
async def demonstrate_trigger_logic(message: Message):
    """
    Demonstrate the new trigger logic for rise-based buying.
    """
    try:
        # Get user's trading client and pair
        client, pair = get_user_client(message.from_user.id)
        
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
        
        demo_info = []
        demo_info.append("🎯 *Trigger Logic Demo*\n")
        
        # Show current market data
        bid_price = bookticker_data.get('bid_price', 'N/A')
        ask_price = bookticker_data.get('ask_price', 'N/A')
        mid_price = (float(bid_price) + float(ask_price)) / 2 if bid_price != 'N/A' and ask_price != 'N/A' else 0
        
        demo_info.append("📊 *Current Market Data:*")
        demo_info.append(f"   • Bid: {bid_price}")
        demo_info.append(f"   • Ask: {ask_price}")
        demo_info.append(f"   • Mid Price: {mid_price:.6f}")
        demo_info.append(f"   • Direction: {'📈 Рост' if direction_info.get('is_rise', False) else '📉 Падение'}")
        
        # Show trigger logic explanation
        demo_info.append("\n🎯 *Trigger Logic:*")
        demo_info.append("1️⃣ При покупке/продаже устанавливается триггер")
        demo_info.append("2️⃣ Если в течение паузы цена только росла - покупаем")
        demo_info.append("3️⃣ После покупки снова устанавливаем триггер")
        demo_info.append("4️⃣ Цикл повторяется при каждом росте")
        
        # Show how it works
        demo_info.append("\n⚡ *How It Works:*")
        demo_info.append("• Покупка на падении: остаётся как раньше")
        demo_info.append("• Покупка на росте: новая логика с триггерами")
        demo_info.append("• Пауза: отсчитывается от триггера")
        demo_info.append("• Множественные покупки: при непрерывном росте")
        
        # Show current status
        demo_info.append("\n🔍 *Current Status:*")
        demo_info.append(f"   • WebSocket: {'✅' if websocket_manager.market_connection else '❌'}")
        demo_info.append(f"   • BookTicker: {'✅' if bookticker_data else '❌'}")
        demo_info.append(f"   • Price History: {len(direction_info.get('price_history', []))} points")
        demo_info.append(f"   • Last Change: {direction_info.get('last_change_time', 0):.1f}s ago")
        
        await message.answer('\n'.join(demo_info), parse_mode='Markdown')
        
    except Exception as e:
        logger.exception(f"Error in trigger demo command: {e}")
        await message.answer(f"❌ Ошибка демонстрации: {str(e)}")


@router.message(Command("trigger_status"))
async def show_trigger_status(message: Message):
    """
    Show current trigger status for the user.
    """
    try:
        user_id = message.from_user.id
        
        # Get user's trading client and pair
        client, pair = get_user_client(user_id)
        
        if not pair:
            await message.answer("❌ Валютная пара не указана. Установите пару в /parameters")
            return

        status_info = []
        status_info.append("📊 *Trigger Status*\n")
        
        # Check autobuy state
        from bot.commands.autobuy import autobuy_states
        
        if user_id in autobuy_states:
            state = autobuy_states[user_id]
            status_info.append("✅ *Autobuy:* Активен")
            status_info.append(f"   • Rise Trigger: {'✅' if state.get('is_rise_trigger', False) else '❌'}")
            status_info.append(f"   • Trigger Price: {state.get('trigger_price', 'None')}")
            status_info.append(f"   • Trigger Time: {state.get('trigger_time', 0):.1f}s ago")
            status_info.append(f"   • Rise Buy Count: {state.get('rise_buy_count', 0)}")
            status_info.append(f"   • Active Orders: {len(state.get('active_orders', []))}")
        else:
            status_info.append("❌ *Autobuy:* Не активен")
        
        # Check bookTicker data
        bookticker_data = websocket_manager.get_current_bookticker(pair)
        if bookticker_data:
            status_info.append(f"\n📈 *Market Data:*")
            status_info.append(f"   • Bid: {bookticker_data.get('bid_price', 'N/A')}")
            status_info.append(f"   • Ask: {bookticker_data.get('ask_price', 'N/A')}")
            status_info.append(f"   • Is Rise: {'✅' if bookticker_data.get('is_rise', False) else '❌'}")
        else:
            status_info.append(f"\n❌ *Market Data:* Недоступно")
        
        await message.answer('\n'.join(status_info), parse_mode='Markdown')
        
    except Exception as e:
        logger.exception(f"Error in trigger status command: {e}")
        await message.answer(f"❌ Ошибка получения статуса: {str(e)}") 