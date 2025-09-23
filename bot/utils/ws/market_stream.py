import json
import asyncio
import time
import aiohttp
from typing import Any, Dict

from bot.logger import logger
from bot.utils.error_notifier import notify_component_error
from bot.utils.ws.pb_decoder import decode_push_message


async def handle_market_message_impl(manager: Any, message: Dict[str, Any]):
    """Handle incoming market data messages. Delegated implementation."""
    try:
        from bot.utils.websocket_handlers import handle_price_update, handle_bookticker_update

        channel = message.get('channel', '')
        symbol = message.get('symbol')

        if isinstance(message, dict) and symbol:
            if 'bookTicker' in channel:
                bookticker_data = message.get('publicbookticker', {})
                if bookticker_data:
                    bid_price = bookticker_data.get('bidprice')
                    ask_price = bookticker_data.get('askprice')
                    bid_qty = bookticker_data.get('bidquantity')
                    ask_qty = bookticker_data.get('askquantity')

                    if bid_price and ask_price:
                        manager.current_bookticker[symbol] = {
                            'bid_price': bid_price,
                            'ask_price': ask_price,
                            'bid_qty': bid_qty,
                            'ask_qty': ask_qty,
                            'timestamp': message.get('sendtime', int(time.time() * 1000)),
                        }

                        # logger.info(f"[MarketWS] BookTicker update for {symbol}: bid={bid_price}, ask={ask_price}")

                        await handle_bookticker_update(symbol, bid_price, ask_price, bid_qty, ask_qty)

                        if symbol in manager.bookticker_callbacks:
                            logger.debug(
                                f"[MarketWS] Found {len(manager.bookticker_callbacks[symbol])} bookTicker callbacks for {symbol}"
                            )
                            for callback in manager.bookticker_callbacks[symbol]:
                                try:
                                    await callback(symbol, bid_price, ask_price, bid_qty, ask_qty)
                                except Exception as e:
                                    logger.error(
                                        f"[MarketWS] Error in bookTicker callback for {symbol}: {e}",
                                        exc_info=True,
                                    )
                        else:
                            logger.debug(f"[MarketWS] No bookTicker callbacks registered for symbol {symbol}")

                        await manager._update_price_direction(symbol, float(bid_price), float(ask_price))

            elif 'deals' in channel:
                deals_data = message.get('publicdeals', {}).get('dealsList', [])
                if deals_data and len(deals_data) > 0:
                    price_data = deals_data[0].get('price')
                    if price_data:
                        logger.debug(f"[MarketWS] Price update for {symbol}: {price_data}")

                        if symbol in manager.price_callbacks:
                            logger.debug(f"[MarketWS] Found {len(manager.price_callbacks[symbol])} callbacks for {symbol}")
                            for callback in manager.price_callbacks[symbol]:
                                try:
                                    logger.debug(
                                        f"[MarketWS] Calling callback {callback.__name__} for {symbol} with price {price_data}"
                                    )
                                    await callback(symbol, price_data)
                                except Exception as e:
                                    logger.error(
                                        f"[MarketWS] Error in price callback for {symbol} ({callback.__name__}): {e}",
                                        exc_info=True,
                                    )
                        else:
                            logger.debug(f"[MarketWS] No callbacks registered for symbol {symbol}")
                    else:
                        logger.warning(
                            f"[MarketWS] Could not extract price from deals array for symbol {symbol}: {message}"
                        )
                else:
                    logger.warning(f"[MarketWS] Could not extract deals array for symbol {symbol}: {message}")

        if message.get("method") == "SUBSCRIPTION" and message.get("code") == 0:
            logger.info(f"[MarketWS] Subscription successful response: {message}")
        elif message.get("code") != 0 and message.get("msg"):
            logger.error(f"[MarketWS] Received error message response from MEXC: {message}")
            try:
                await notify_component_error("вебсокетах (рынок)", f"Получено сообщение об ошибке: {message}")
            except Exception:
                pass
        elif not symbol:
            logger.debug(f"[MarketWS] Received non-symbol or unrecognized market message: {message}")

    except Exception as e:
        logger.error(f"Error handling market message: {e}")


async def listen_market_messages_impl(manager: Any):
    if not manager.market_connection or not manager.market_connection.get('ws'):
        logger.error("[MarketWS] Market connection or WebSocket not established for listening.")
        manager.market_listener_active = False
        return

    if manager.market_listener_active and hasattr(manager, '_market_listener_started'):
        logger.warning("[MarketWS] Market listener already active, avoiding duplicate")
        return

    manager._market_listener_started = True
    ws = manager.market_connection['ws']
    logger.info(f"[MarketWS] Starting to listen for market messages")

    manager.reconnect_delay = 1
    ping_task = asyncio.create_task(manager._ping_market_loop(ws))

    try:
        while not manager.is_shutting_down and manager.market_connection and not ws.closed:
            try:
                msg = await ws.receive(timeout=60)
            except asyncio.TimeoutError:
                connection_age = time.time() - manager.market_connection.get('created_at', time.time())
                logger.debug(f"[MarketWS] Timeout after {connection_age:.1f}s - no messages from MEXC for 60 seconds")
                if ws.closed:
                    logger.warning("[MarketWS] WebSocket closed during receive timeout.")
                    break
                continue
            except Exception as e:
                connection_age = time.time() - manager.market_connection.get('created_at', time.time())
                logger.error(f"[MarketWS] Error receiving message after {connection_age:.1f}s: {e}")
                break

            if msg.type == aiohttp.WSMsgType.TEXT:
                try:
                    data = json.loads(msg.data)
                    # Handle control messages first to avoid noisy logging
                    if data.get("msg") == "PONG":
                        # logger.debug(f"[MarketWS] PONG: {data}")
                        continue
                    if 'pong' in data:
                        # logger.debug(f"[MarketWS] PONG: {data}")
                        continue

                    if not ('s' in data and 'c' in data):
                        logger.debug(f"[MarketWS] 📨 Received control/non-symbol message: {data}")

                    if 'pong' in data:
                        # logger.warning(f"[MarketWS] 🏓 Received PONG from server: {data}")
                        continue
                    if 'ping' in data:
                        try:
                            pong_response = {"pong": data['ping']}
                            await ws.send_json(pong_response)
                            logger.warning(f"[MarketWS] 🏓 Received PING {data['ping']}, sent PONG")
                        except Exception as e:
                            logger.error(f"[MarketWS] Failed to send PONG: {e}")
                            break
                        continue

                    # handled above

                    if data.get("method") == "SUBSCRIPTION":
                        if data.get("code") == 0:
                            logger.info(f"[MarketWS] Subscription successful: {data.get('params', [])}")
                        else:
                            logger.error(f"[MarketWS] Subscription failed: {data}")
                        continue

                    if data.get("code") is not None and data.get("code") != 0:
                        logger.error(f"[MarketWS] Received error from MEXC: {data}")
                        try:
                            await notify_component_error("вебсокетах (рынок)", f"Ошибка от MEXC: {data}")
                        except Exception:
                            pass
                        continue

                    await handle_market_message_impl(manager, data)

                except json.JSONDecodeError as e:
                    logger.error(f"[MarketWS] JSON decode error: {e}")
                    continue
                except Exception as e:
                    logger.error(f"[MarketWS] Error processing message: {e}")
                    continue

            elif msg.type == aiohttp.WSMsgType.BINARY:
                try:
                    data = decode_push_message(msg.data)
                    if data is None:
                        logger.error("[MarketWS] Failed to decode protobuf binary market message")
                        continue
                    await handle_market_message_impl(manager, data)
                except Exception as e:
                    logger.error(f"[MarketWS] Error processing binary message: {e}")
                    continue
            elif msg.type == aiohttp.WSMsgType.CLOSED:
                connection_age = time.time() - manager.market_connection.get('created_at', time.time())
                logger.warning(
                    f"[MarketWS] WebSocket closed. Code: {ws.close_code}, Reason: {msg.data}, Age: {connection_age:.1f}s"
                )
                break

            elif msg.type == aiohttp.WSMsgType.ERROR:
                connection_age = time.time() - manager.market_connection.get('created_at', time.time())
                logger.error(f"[MarketWS] WebSocket error after {connection_age:.1f}s: {ws.exception()}")
                break

            elif msg.type == aiohttp.WSMsgType.CLOSING:
                logger.info("[MarketWS] WebSocket is closing, waiting for clean shutdown...")
                for _ in range(50):
                    if ws.closed:
                        break
                    await asyncio.sleep(0.1)
                break

    except (asyncio.CancelledError, GeneratorExit):
        logger.info("[MarketWS] Market listener task cancelled")
    except Exception as e:
        logger.error(f"[MarketWS] Unexpected error in _listen_market_messages: {e}", exc_info=True)
    finally:
        if 'ping_task' in locals():
            ping_task.cancel()
            try:
                await ping_task
            except asyncio.CancelledError:
                pass

        manager.market_listener_active = False
        if hasattr(manager, '_market_listener_started'):
            delattr(manager, '_market_listener_started')
        logger.info("[MarketWS] Market WebSocket listener stopped")

