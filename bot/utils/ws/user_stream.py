import json
import asyncio
import time
import aiohttp
from typing import Any, Dict

from logger import logger
from bot.utils.ws.pb_decoder import decode_push_message


async def listen_user_messages_impl(manager: Any, user_id: int):
    if user_id not in manager.user_connections:
        return

    ws = manager.user_connections[user_id]['ws']
    ping_task = asyncio.create_task(manager._ping_user_loop(ws, user_id))

    try:
        from bot.utils.websocket_handlers import update_order_status

        while not manager.is_shutting_down and user_id in manager.user_connections:
            try:
                msg = await ws.receive(timeout=60)
            except asyncio.TimeoutError:
                connection_age = time.time() - manager.user_connections[user_id].get('created_at', time.time())
                logger.debug(
                    f"[UserWS] Timeout for user {user_id} after {connection_age:.1f}s - no messages from MEXC for 60 seconds"
                )
                if ws.closed:
                    logger.warning(f"WebSocket for user {user_id} closed during receive timeout.")
                    break
                continue

            if msg.type == aiohttp.WSMsgType.TEXT:
                try:
                    data = json.loads(msg.data)
                except json.JSONDecodeError as e:
                    logger.error(f"JSON decode error for user {user_id}: {e}, data: {msg.data[:200]}")
                    continue

                if not (
                    'c' in data and data.get('c') in [
                        'spot@private.orders.v3.api.pb',
                        'spot@private.account.v3.api.pb',
                    ]
                ):
                    # logger.info(f"[UserWS] 📨 Received message for user {user_id}: {data}")
                    pass

                if data.get("msg") == "PONG":
                    # logger.warning(f"[UserWS] 🏓 Received PONG response for user {user_id}: {data}")
                    continue

                if 'id' in data and 'code' in data:
                    logger.debug(f"Сервисное сообщение для {user_id}: {data}")
                    continue

                if 'pong' in data:
                    logger.warning(f"[UserWS] 🏓 Received PONG from server for user {user_id}")
                    continue

                if 'ping' in data:
                    try:
                        pong_msg = {'pong': data['ping']}
                        await ws.send_str(json.dumps(pong_msg))
                        logger.warning(
                            f"[UserWS] 🏓 Received PING {data['ping']}, sent PONG for user {user_id}"
                        )
                    except Exception as e:
                        logger.error(f"[UserWS] Failed to send PONG for user {user_id}: {e}")
                        break
                    continue

                channel = data.get('c')
                logger.debug(f"User {user_id} received message on channel: {channel}")

                if channel == "spot@private.orders.v3.api.pb":
                    order_data = data.get('d', {})
                    symbol = data.get('s')
                    order_id = order_data.get('i')
                    status_code = order_data.get('s')

                    status_map = {1: "NEW", 2: "FILLED", 3: "PARTIALLY_FILLED", 4: "CANCELED", 5: "REJECTED"}
                    status = status_map.get(status_code, "UNKNOWN")

                    logger.info(
                        f"Обновление ордера {order_id} для пользователя {user_id}: {symbol} - {status} (код: {status_code})"
                    )

                    try:
                        await update_order_status(order_id, symbol, status)
                    except Exception as e:
                        logger.error(f"Ошибка обновления статуса ордера: {e}")

                elif channel == "spot@private.account.v3.api.pb":
                    account_data = data.get('d', {})
                    asset = account_data.get('a')
                    free = account_data.get('f')
                    locked = account_data.get('l')

                    logger.info(
                        f"Обновление баланса для {user_id}: {asset} - свободно: {free}, заблокировано: {locked}"
                    )
                else:
                    logger.debug(f"Неизвестный канал для {user_id}: {channel}, данные: {json.dumps(data)}")

            elif msg.type == aiohttp.WSMsgType.BINARY:
                try:
                    data = decode_push_message(msg.data)
                except Exception as e:
                    logger.error(f"[UserWS] Failed to decode binary protobuf for user {user_id}: {e}")
                    continue

                if not data:
                    continue

                channel = data.get('c')
                logger.debug(f"User {user_id} received message on channel: {channel}")

                if channel == "spot@private.orders.v3.api.pb":
                    order_data = data.get('d', {})
                    symbol = data.get('s')
                    order_id = order_data.get('i')
                    status_code = order_data.get('s')
                    status_map = {1: "NEW", 2: "FILLED", 3: "PARTIALLY_FILLED", 4: "CANCELED", 5: "REJECTED"}
                    status = status_map.get(status_code, "UNKNOWN")
                    logger.info(
                        f"Обновление ордера {order_id} для пользователя {user_id}: {symbol} - {status} (код: {status_code})"
                    )
                    try:
                        await update_order_status(order_id, symbol, status)
                    except Exception as e:
                        logger.error(f"Ошибка обновления статуса ордера: {e}")

                elif channel == "spot@private.account.v3.api.pb":
                    account_data = data.get('d', {})
                    asset = account_data.get('a')
                    free = account_data.get('f')
                    locked = account_data.get('l')
                    logger.info(
                        f"Обновление баланса для {user_id}: {asset} - свободно: {free}, заблокировано: {locked}"
                    )
                else:
                    logger.debug(f"Неизвестный канал для {user_id}: {channel}, данные: {json.dumps(data)}")

            elif msg.type == aiohttp.WSMsgType.CLOSED:
                connection_age = time.time() - manager.user_connections[user_id].get('created_at', time.time())
                logger.warning(
                    f"WebSocket for user {user_id} closed. Code: {ws.close_code}, Reason: {msg.data}, Age: {connection_age:.1f}s"
                )
                break

            elif msg.type == aiohttp.WSMsgType.ERROR:
                connection_age = time.time() - manager.user_connections[user_id].get('created_at', time.time())
                logger.error(f"WebSocket error for user {user_id} after {connection_age:.1f}s: {ws.exception()}")
                break
            elif msg.type == aiohttp.WSMsgType.CLOSING:
                logger.info(f"WebSocket for user {user_id} is closing")
                await asyncio.sleep(1)
                if ws.closed:
                    break
    except (asyncio.CancelledError, GeneratorExit):
        logger.info(f"WebSocket listener task cancelled for user {user_id}")
    except json.JSONDecodeError as e:
        logger.error(f"JSON decode error in WebSocket for user {user_id}: {e}")
    except Exception as e:
        logger.error(f"Error in user WebSocket for {user_id}: {e}")
    finally:
        if 'ping_task' in locals():
            ping_task.cancel()
            try:
                await ping_task
            except asyncio.CancelledError:
                pass
        logger.info(f"User {user_id} WebSocket listener stopped")

