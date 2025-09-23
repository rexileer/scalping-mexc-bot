import asyncio
from aiogram import Router
from aiogram.types import Message
from aiogram.filters import Command

from bot.utils.mexc import get_user_client
from bot.utils.websocket_manager import websocket_manager
from bot.commands.autobuy import autobuy_states, trigger_states
from bot.logger import logger
import time

router = Router()


@router.message(Command("trigger_debug"))
async def debug_trigger_logic(message: Message):
    """
    Debug command to show trigger logic status and bookTicker data.
    """
    try:
        # Get user's trading client and pair
        client, pair = get_user_client(message.from_user.id)
        
        if not pair:
            await message.answer("❌ Валютная пара не указана. Установите пару в /parameters")
            return

        user_id = message.from_user.id
        debug_info = []
        debug_info.append("🔍 *Trigger Debug Information*\n")

        # Check if user is in autobuy
        if user_id in autobuy_states:
            state = autobuy_states[user_id]
            debug_info.append("✅ *Autobuy State:* Активен")
            debug_info.append(f"   • Last Buy Price: {state.get('last_buy_price', 'None')}")
            debug_info.append(f"   • Current Price: {state.get('current_price', 'None')}")
            debug_info.append(f"   • Active Orders: {len(state.get('active_orders', []))}")
            debug_info.append(f"   • Waiting Opportunity: {state.get('waiting_for_opportunity', False)}")
            debug_info.append(f"   • Is Rise Trigger: {state.get('is_rise_trigger', False)}")
            debug_info.append(f"   • Trigger Price: {state.get('trigger_price', 'None')}")
            debug_info.append(f"   • Trigger Time: {state.get('trigger_time', 0)}")
            debug_info.append(f"   • Rise Buy Count: {state.get('rise_buy_count', 0)}")
        else:
            debug_info.append("❌ *Autobuy State:* Не активен")

        # Check bookTicker data
        bookticker_data = websocket_manager.get_current_bookticker(pair)
        if bookticker_data:
            debug_info.append(f"\n📊 *BookTicker Data:*")
            debug_info.append(f"   • Bid Price: {bookticker_data.get('bid_price', 'N/A')}")
            debug_info.append(f"   • Ask Price: {bookticker_data.get('ask_price', 'N/A')}")
            debug_info.append(f"   • Bid Qty: {bookticker_data.get('bid_qty', 'N/A')}")
            debug_info.append(f"   • Ask Qty: {bookticker_data.get('ask_qty', 'N/A')}")
            debug_info.append(f"   • Is Rise: {bookticker_data.get('is_rise', 'N/A')}")
            debug_info.append(f"   • Last Change Time: {bookticker_data.get('last_change_time', 'N/A')}")
            debug_info.append(f"   • Current Price: {bookticker_data.get('current_price', 'N/A')}")
        else:
            debug_info.append(f"\n❌ *BookTicker Data:* Недоступно")

        # Check price direction
        direction_info = websocket_manager.get_price_direction(pair)
        debug_info.append(f"\n📈 *Price Direction:*")
        debug_info.append(f"   • Is Rise: {direction_info.get('is_rise', False)}")
        debug_info.append(f"   • Last Change Time: {direction_info.get('last_change_time', 0)}")
        debug_info.append(f"   • Current Price: {direction_info.get('current_price', 0)}")
        debug_info.append(f"   • Price History Length: {len(direction_info.get('price_history', []))}")

        # Check WebSocket connection
        debug_info.append(f"\n🔗 *WebSocket Status:*")
        debug_info.append(f"   • Market Connection: {'✅' if websocket_manager.market_connection else '❌'}")
        debug_info.append(f"   • BookTicker Subscriptions: {len(websocket_manager.bookticker_subscriptions)}")
        debug_info.append(f"   • Market Subscriptions: {len(websocket_manager.market_subscriptions)}")

        await message.answer('\n'.join(debug_info), parse_mode='Markdown')
        
    except Exception as e:
        logger.exception(f"Error in trigger debug command: {e}")
        await message.answer(f"❌ Ошибка отладки триггеров: {str(e)}")


@router.message(Command("trigger_test"))
async def test_trigger_logic(message: Message):
    """
    Test trigger logic by simulating a trigger setup.
    """
    try:
        user_id = message.from_user.id
        
        if user_id not in autobuy_states:
            await message.answer("❌ Автобай не активен. Запустите автобай сначала.")
            return

        # Get current bookTicker data
        client, pair = get_user_client(user_id)
        bookticker_data = websocket_manager.get_current_bookticker(pair)
        
        if not bookticker_data:
            await message.answer("❌ Нет данных bookTicker. Проверьте WebSocket соединение.")
            return

        # Simulate trigger setup
        state = autobuy_states[user_id]
        mid_price = (float(bookticker_data['bid_price']) + float(bookticker_data['ask_price'])) / 2
        current_time = time.time()
        
        # Set trigger
        state['trigger_price'] = mid_price
        state['trigger_time'] = current_time
        state['is_rise_trigger'] = True
        state['is_trigger_activated'] = False
        state['trigger_activated_time'] = 0
        state['pause_trend_prices'] = []
        state['trend_only_rise'] = True
        state['last_pause_price'] = None
        
        test_info = []
        test_info.append("🧪 *Trigger Test Results*\n")
        test_info.append(f"✅ Триггер установлен:")
        test_info.append(f"   • Цена триггера: {mid_price:.6f}")
        test_info.append(f"   • Время установки: {current_time}")
        test_info.append(f"   • Статус: Активен")
        test_info.append(f"\n📊 Текущие данные:")
        test_info.append(f"   • Bid: {bookticker_data['bid_price']}")
        test_info.append(f"   • Ask: {bookticker_data['ask_price']}")
        test_info.append(f"   • Направление: {'Рост' if bookticker_data.get('is_rise', False) else 'Падение'}")
        
        await message.answer('\n'.join(test_info), parse_mode='Markdown')
        
    except Exception as e:
        logger.exception(f"Error in trigger test command: {e}")
        await message.answer(f"❌ Ошибка тестирования триггера: {str(e)}") 