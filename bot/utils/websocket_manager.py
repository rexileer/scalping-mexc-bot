import asyncio
import json
import time
import logging
import aiohttp
from typing import Dict, List, Optional, Callable, Any, Tuple
import hmac
import hashlib

from users.models import User
from logger import logger
from bot.utils.ws.pb_decoder import decode_push_message
from bot.utils.ws.price_direction import PriceDirectionTracker
from bot.utils.ws.market_stream import handle_market_message_impl
from bot.utils.ws.market_stream import listen_market_messages_impl
from bot.utils.ws.user_stream import listen_user_messages_impl


class MexcWebSocketManager:
    """Class to manage WebSocket connections to MEXC exchange."""

    BASE_URL = "ws://wbs-api.mexc.com/ws"
    REST_API_URL = "https://api.mexc.com"

    def __init__(self):
        self.user_connections: Dict[int, Dict] = {}  # {user_id: {'ws': websocket, 'listen_key': key}}
        self.market_connection = None
        self.market_subscriptions: List[str] = []
        self.bookticker_subscriptions: List[str] = []  # Track bookTicker subscriptions separately
        self.market_connection_task = None
        self.ping_tasks: Dict[int, asyncio.Task] = {}
        self.price_callbacks: Dict[str, List[Callable]] = {}  # {symbol: [callbacks]}
        self.bookticker_callbacks: Dict[str, List[Callable]] = {}  # {symbol: [callbacks for bid/ask]}
        self.current_bookticker: Dict[str, Dict] = {}  # {symbol: {'bid_price': x, 'ask_price': y, 'bid_qty': z, 'ask_qty': w}}
        self.reconnect_delay = 1  # Initial reconnect delay in seconds
        self.is_shutting_down = False
        self.reconnecting_users = set()  # Set to track users currently in reconnection process
        self.market_connection_lock = asyncio.Lock()  # Блокировка для market connection
        self.market_listener_active = False  # Флаг активного listener
        # Трекер направления цены (рост/падение)
        self.direction_tracker = PriceDirectionTracker(max_history_size=100)

    async def get_listen_key(self, api_key: str, api_secret: str) -> Tuple[bool, str, Optional[str]]:
        """
        Get a listen key for user data streams.

        Returns:
            Tuple[bool, str, Optional[str]]: (success, error_message, listen_key)
        """
        endpoint = "/api/v3/userDataStream"
        url = f"{self.REST_API_URL}{endpoint}"

        # Generate timestamp and signature for authentication
        timestamp = int(time.time() * 1000)
        query_string = f"timestamp={timestamp}"
        signature = hmac.new(
            api_secret.encode(),
            query_string.encode(),
            hashlib.sha256
        ).hexdigest()

        headers = {
            "X-MEXC-APIKEY": api_key,
            "Content-Type": "application/json"
        }

        # Add timestamp and signature to the URL
        request_url = f"{url}?{query_string}&signature={signature}"

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(request_url, headers=headers) as response:
                    response_text = await response.text()
                    logger.info(f"Listen key API response: {response.status} - {response_text}")

                    if response.status != 200:
                        # Обрабатываем ошибку связанную с IP ограничениями
                        if "700006" in response_text and "ip white list" in response_text.lower():
                            error_msg = "IP адрес сервера не добавлен в белый список API ключа. Пожалуйста, настройте IP ограничения в настройках ключа на MEXC."
                            logger.warning(f"IP whitelist error for listen key: {response_text}")
                            return False, error_msg, None

                        error_text = f"Failed to get listen key: {response_text}"
                        logger.error(error_text)
                        return False, error_text, None

                    try:
                        data = json.loads(response_text)
                        listen_key = data.get("listenKey")
                        if listen_key:
                            return True, "", listen_key
                        else:
                            return False, "No listen key in response", None
                    except json.JSONDecodeError:
                        return False, f"Invalid JSON response: {response_text}", None
        except Exception as e:
            error_msg = f"Error getting listen key: {str(e)}"
            logger.error(error_msg)
            return False, error_msg, None

    async def keep_listen_key_alive(self, user_id: int, api_key: str, api_secret: str):
        """Keep the listen key alive with periodic pings."""
        while user_id in self.user_connections and not self.is_shutting_down:
            try:
                listen_key = self.user_connections[user_id].get('listen_key')
                if not listen_key:
                    logger.warning(f"No listen key found for user {user_id}")
                    await asyncio.sleep(60)
                    continue

                endpoint = "/api/v3/userDataStream"
                url = f"{self.REST_API_URL}{endpoint}"

                # Generate timestamp and signature for authentication
                timestamp = int(time.time() * 1000)
                query_string = f"timestamp={timestamp}&listenKey={listen_key}"
                signature = hmac.new(
                    api_secret.encode(),
                    query_string.encode(),
                    hashlib.sha256
                ).hexdigest()

                headers = {
                    "X-MEXC-APIKEY": api_key,
                    "Content-Type": "application/json"
                }

                # Add timestamp and signature to the URL
                request_url = f"{url}?{query_string}&signature={signature}"

                async with aiohttp.ClientSession() as session:
                    async with session.put(request_url, headers=headers) as response:
                        if response.status != 200:
                            error_text = await response.text()
                            logger.error(f"Failed to extend listen key: {error_text}")

                # MEXC documentation says listen keys are valid for 60 minutes
                # we'll refresh every 45 minutes to be safe
                await asyncio.sleep(45 * 60)
            except Exception as e:
                logger.error(f"Error in keep_listen_key_alive for user {user_id}: {e}")
                await asyncio.sleep(60)  # Wait before retry

    async def send_ping(self, ws):
        """Send ping message to keep connection alive."""
        try:
            # MEXC WebSocket requires a specific PING format
            ping_msg = {"ping": int(time.time() * 1000)}
            await ws.send_str(json.dumps(ping_msg))
            logger.debug("Sent PING message")
        except Exception as e:
            logger.error(f"Error sending ping: {e}")

    async def ping_loop(self, ws, user_id: Optional[int] = None):
        """Periodically send ping messages to keep the connection alive."""
        connection_type = f"user {user_id}" if user_id else "market"
        logger.debug(f"Starting ping loop for {connection_type}")

        while (not self.is_shutting_down and
               ((user_id is not None and user_id in self.user_connections) or
                (user_id is None and self.market_connection is not None))):
            try:
                # Проверяем состояние соединения перед отправкой ping
                if ws.closed:
                    logger.debug(f"WebSocket closed in ping loop for {connection_type}")
                    break

                # Проверяем closing только если атрибут существует
                if hasattr(ws, 'closing') and ws.closing:
                    logger.debug(f"WebSocket closing in ping loop for {connection_type}")
                    break

                # Дополнительная проверка на закрытое соединение
                if hasattr(ws, '_transport') and ws._transport and hasattr(ws._transport, 'is_closing') and ws._transport.is_closing():
                    logger.debug(f"Transport is closing for {connection_type}")
                    break

                await self.send_ping(ws)
                await asyncio.sleep(20)  # Send ping every 20 seconds

            except (ConnectionResetError, ConnectionAbortedError, OSError) as e:
                logger.debug(f"Connection error in ping loop for {connection_type}: {e}")
                break
            except Exception as e:
                logger.error(f"Unexpected error in ping loop for {connection_type}: {e}")
                break

        logger.debug(f"Ping loop stopped for {connection_type}")

    async def handle_market_message(self, message: dict):
        """Handle incoming market data messages."""
        await handle_market_message_impl(self, message)

    async def _update_price_direction(self, symbol: str, bid_price: float, ask_price: float):
        """Delegate price direction tracking to tracker."""
        try:
            await self.direction_tracker.update(symbol, bid_price, ask_price)
        except Exception as e:
            logger.error(f"Error updating price direction for {symbol}: {e}")

    def get_price_direction(self, symbol: str) -> Dict[str, Any]:
        """
        Возвращает информацию о направлении цены для символа.

        Returns:
            Dict с ключами:
            - is_rise: bool - текущее направление (True = рост, False = падение)
            - last_change_time: float - время последнего изменения направления
            - current_price: float - текущая средняя цена
            - price_history: List[float] - история цен (последние N значений)
        """
        return self.direction_tracker.get(symbol)

    async def connect_user_data_stream(self, user_id: int) -> bool:
        """Connect to user data stream for a specific user."""
        # Проверяем, не идет ли уже процесс переподключения
        if user_id in self.reconnecting_users:
            logger.debug(f"User {user_id} is already in reconnection process. Skipping.")
            return True

        # Добавляем пользователя в список переподключающихся
        self.reconnecting_users.add(user_id)

        try:
            # Отключаем существующее соединение
            if user_id in self.user_connections:
                await self.disconnect_user(user_id)
                await asyncio.sleep(0.5)

            user = await User.objects.aget(telegram_id=user_id)

            if not user.api_key or not user.api_secret:
                logger.warning(f"User {user_id} missing API keys")
                return False

            # Получаем listen key
            success, error_message, listen_key = await self.get_listen_key(user.api_key, user.api_secret)
            if not success:
                logger.error(f"Error getting listen key for user {user_id}: {error_message}")
                return False

            ws_url = f"{self.BASE_URL}?listenKey={listen_key}"

            # Создаем сессию с оптимизированными настройками
            timeout = aiohttp.ClientTimeout(total=30)
            session = aiohttp.ClientSession(
                timeout=timeout,
                connector=aiohttp.TCPConnector(
                    limit=50,
                    limit_per_host=10,
                    keepalive_timeout=30,
                    enable_cleanup_closed=True
                )
            )

            try:
                ws = await session.ws_connect(
                    ws_url,
                    heartbeat=None,  # MEXC сам отправляет PING
                    compress=False
                )
            except Exception as e:
                await session.close()
                logger.error(f"Error connecting WebSocket for user {user_id}: {e}")
                return False

            # Сохраняем информацию о соединении
            self.user_connections[user_id] = {
                'ws': ws,
                'session': session,
                'listen_key': listen_key,
                'tasks': [],
                'created_at': time.time(),
                'reconnect_count': 0
            }

            # НЕ запускаем ping loop для user connections - MEXC сам отправляет PING
            # ping_task = asyncio.create_task(self.ping_loop(ws, user_id))
            # self.ping_tasks[user_id] = ping_task
            # self.user_connections[user_id]['tasks'].append(ping_task)

            # Запускаем keep alive для listen key
            keep_alive_task = asyncio.create_task(
                self.keep_listen_key_alive(user_id, user.api_key, user.api_secret)
            )
            self.user_connections[user_id]['tasks'].append(keep_alive_task)

            # Запускаем прослушивание сообщений
            listen_task = asyncio.create_task(self._listen_user_messages(user_id))
            self.user_connections[user_id]['tasks'].append(listen_task)

            # Подписываемся на ордера с задержкой
            await asyncio.sleep(0.5)
            await self.subscribe_user_orders(user_id)

            logger.info(f"Connected user {user_id} to WebSocket")
            return True

        except Exception as e:
            logger.error(f"Error connecting user {user_id} to WebSocket: {e}")
            return False
        finally:
            # Всегда убираем из списка переподключающихся
            self.reconnecting_users.discard(user_id)

    async def _listen_user_messages(self, user_id: int):
        """Listen for messages from user data stream."""
        await listen_user_messages_impl(self, user_id)

    async def connect_market_data(self, symbols: List[str] = None):
        """
        Connect to market data stream and subscribe to specified symbols.
        If no symbols are provided, will use existing subscriptions.
        """
        async with self.market_connection_lock:
            # Проверяем, есть ли уже здоровое соединение
            if self.market_connection:
                ws = self.market_connection.get('ws')
                if ws and not ws.closed:
                    logger.debug("Market connection already exists and is healthy")
                    # Если нужно добавить новые символы к существующему соединению
                    if symbols:
                        new_symbols = [s for s in symbols if s not in self.market_subscriptions]
                        if new_symbols:
                            await self.subscribe_market_data(new_symbols)
                            await self.subscribe_bookticker_data(new_symbols)
                    return True

                # Если соединение нездоровое, отключаем его
                await self.disconnect_market()
                await asyncio.sleep(0.5)

            try:
                logger.info(f"[MarketWS] Starting connection to {self.BASE_URL}")

                # Создаем новую сессию с правильными настройками
                timeout = aiohttp.ClientTimeout(total=30)
                session = aiohttp.ClientSession(
                    timeout=timeout,
                    connector=aiohttp.TCPConnector(
                        limit=100,
                        limit_per_host=30,
                        keepalive_timeout=30,
                        enable_cleanup_closed=True
                    )
                )
                logger.debug("[MarketWS] Created session with optimized settings")

                ws = await session.ws_connect(
                    self.BASE_URL,
                    # НЕ используем автоматический heartbeat - MEXC сам отправляет PING
                    heartbeat=None,
                    compress=False  # Отключаем сжатие для стабильности
                )
                logger.info(f"[MarketWS] WebSocket connected successfully")

                self.market_connection = {
                    'ws': ws,
                    'session': session,
                    'created_at': time.time(),
                    'last_ping': time.time(),
                    'reconnect_count': 0
                }
                logger.debug("[MarketWS] Market connection object created")

                # НЕ запускаем ping loop - MEXC сам отправляет PING, мы отвечаем PONG
                # self.market_connection_task = asyncio.create_task(self.ping_loop(ws))

                # Subscribe to symbols if provided
                if symbols:
                    logger.info(f"[MarketWS] Subscribing to provided symbols: {symbols}")
                    # Небольшая задержка перед подпиской
                    await asyncio.sleep(0.5)
                    await self.subscribe_market_data(symbols)
                    await self.subscribe_bookticker_data(symbols)
                elif self.market_subscriptions:
                    logger.info(f"[MarketWS] Reusing existing subscriptions: {self.market_subscriptions}")
                    # Reuse existing subscriptions
                    await asyncio.sleep(0.5)
                    await self.subscribe_market_data(self.market_subscriptions)
                    await self.subscribe_bookticker_data(self.bookticker_subscriptions)

                # Start listening for messages только если не запущен
                if not self.market_listener_active:
                    logger.debug("[MarketWS] Starting market message listener")
                    self.market_listener_active = True
                    asyncio.create_task(self._listen_market_messages())

                logger.info("Connected to market data WebSocket")
                return True

            except Exception as e:
                logger.error(f"Error connecting to market data WebSocket: {e}")
                # Cleanup on error
                if 'session' in locals():
                    try:
                        await session.close()
                        logger.debug("Cleaned up session after connection error")
                    except Exception as cleanup_error:
                        logger.debug(f"Error during session cleanup: {cleanup_error}")
                return False

    async def subscribe_market_data(self, symbols: List[str]):
        """Subscribe to market data for specific symbols."""
        if not self.market_connection:
            logger.error("Market connection not established - cannot subscribe to market data")
            logger.debug(f"Attempted to subscribe to symbols: {symbols}")
            return False

        try:
            ws = self.market_connection['ws']

            # Format subscription parameters for each symbol
            # According to MEXC documentation, the format for deals is:
            # spot@public.deals.v3.api@BTCUSDT
            params = [f"spot@public.aggre.deals.v3.api.pb@100ms@{symbol.upper()}" for symbol in symbols]

            # Send subscription request with unique ID for tracking
            subscription_msg = {
                "method": "SUBSCRIPTION",
                "params": params,
                "id": int(time.time() * 1000)  # Unique ID for tracking
            }

            logger.info(f"[MarketWS] Sending market data subscription request: {subscription_msg}")
            await ws.send_str(json.dumps(subscription_msg))

            # Store subscriptions
            self.market_subscriptions = list(set(self.market_subscriptions + symbols))

            logger.info(f"Subscribed to market data for: {symbols}")
            return True
        except Exception as e:
            logger.error(f"Error subscribing to market data: {e}")
            return False

    async def subscribe_bookticker_data(self, symbols: List[str]):
        """Subscribe to bookTicker data for specific symbols to get best bid/ask prices."""
        if not self.market_connection:
            logger.error("Market connection not established for bookTicker subscription")
            return False

        try:
            ws = self.market_connection['ws']

            # Format subscription parameters for each symbol
            # According to MEXC documentation, the format for bookTicker is:
            # spot@public.bookTicker.v3.api@BTCUSDT
            params = [f"spot@public.aggre.bookTicker.v3.api.pb@100ms@{symbol.upper()}" for symbol in symbols]

            # Send subscription request with unique ID for tracking
            subscription_msg = {
                "method": "SUBSCRIPTION",
                "params": params,
                "id": int(time.time() * 1000)  # Unique ID for tracking
            }

            logger.info(f"[MarketWS] Sending bookTicker subscription request: {subscription_msg}")
            await ws.send_str(json.dumps(subscription_msg))

            # Store bookTicker subscriptions
            self.bookticker_subscriptions = list(set(self.bookticker_subscriptions + symbols))

            logger.info(f"Subscribed to bookTicker data for: {symbols}")
            return True
        except Exception as e:
            logger.error(f"Error subscribing to bookTicker data: {e}")
            return False

    async def _listen_market_messages(self):
        """Listen for messages from market data stream."""
        await listen_market_messages_impl(self)

    async def _ping_market_loop(self, ws):
        """Отправляет PING каждые 30 секунд для поддержания market соединения"""
        try:
            while not ws.closed and not self.is_shutting_down:
                await asyncio.sleep(30)  # Пинг каждые 30 секунд (MEXC дисконнектит через 60)

                if ws.closed or self.is_shutting_down:
                    break

                try:
                    # Используем официальный формат MEXC согласно документации
                    ping_message = {"method": "PING"}
                    await ws.send_json(ping_message)
                    # logger.info(f"[MarketWS] 📡 Sent PING (official format)")
                except Exception as e:
                    logger.error(f"[MarketWS] Failed to send PING: {e}")
                    break

        except asyncio.CancelledError:
            logger.debug("[MarketWS] Ping loop cancelled")
        except Exception as e:
            logger.error(f"[MarketWS] Ping loop error: {e}")

    async def _ping_user_loop(self, ws, user_id: int):
        """Отправляет PING каждые 30 секунд для поддержания user соединения"""
        try:
            while not ws.closed and not self.is_shutting_down and user_id in self.user_connections:
                await asyncio.sleep(30)  # Пинг каждые 30 секунд (MEXC дисконнектит через 60)

                if ws.closed or self.is_shutting_down or user_id not in self.user_connections:
                    break

                try:
                    # Используем официальный формат MEXC согласно документации
                    ping_message = {"method": "PING"}
                    await ws.send_str(json.dumps(ping_message))
                    # logger.info(f"[UserWS] 📡 Sent PING (official format) to user {user_id}")
                except Exception as e:
                    logger.error(f"[UserWS] Failed to send PING to user {user_id}: {e}")
                    break

        except asyncio.CancelledError:
            logger.debug(f"[UserWS] Ping loop cancelled for user {user_id}")
        except Exception as e:
            logger.error(f"[UserWS] Ping loop error for user {user_id}: {e}")

    async def register_price_callback(self, symbol: str, callback: Callable[[str, Any], None]):
        """Register a callback function for price updates."""
        if symbol not in self.price_callbacks:
            self.price_callbacks[symbol] = []

        self.price_callbacks[symbol].append(callback)

        # Ensure we're subscribed to this symbol
        if self.market_connection and symbol not in self.market_subscriptions:
            await self.subscribe_market_data([symbol])

    async def register_bookticker_callback(self, symbol: str, callback: Callable[[str, str, str, str, str], Any]):
        """Register a callback function for bookTicker updates (bid/ask prices)."""
        if symbol not in self.bookticker_callbacks:
            self.bookticker_callbacks[symbol] = []

        self.bookticker_callbacks[symbol].append(callback)

        # Ensure we're subscribed to this symbol
        if self.market_connection and symbol not in self.bookticker_subscriptions:
            await self.subscribe_bookticker_data([symbol])

    def get_current_bookticker(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Get current best bid/ask prices for a symbol."""
        bookticker_data = self.current_bookticker.get(symbol)
        if bookticker_data:
            # Добавляем информацию о направлении цены
            direction_info = self.get_price_direction(symbol)
            return {**bookticker_data, **direction_info}
        return None

    def get_current_bid_ask(self, symbol: str) -> Optional[Tuple[str, str]]:
        """Get current best bid and ask prices for a symbol as a tuple."""
        bookticker = self.current_bookticker.get(symbol)
        if bookticker:
            bid_price = bookticker.get('bid_price')
            ask_price = bookticker.get('ask_price')
            if bid_price and ask_price:
                return bid_price, ask_price
        return None

    async def unregister_bookticker_callback(self, symbol: str, callback: Callable):
        """Unregister a specific bookTicker callback."""
        if symbol in self.bookticker_callbacks and callback in self.bookticker_callbacks[symbol]:
            self.bookticker_callbacks[symbol].remove(callback)
            logger.debug(f"Unregistered bookTicker callback for {symbol}")

    async def unregister_price_callback(self, symbol: str, callback: Callable):
        """Unregister a specific price callback."""
        if symbol in self.price_callbacks and callback in self.price_callbacks[symbol]:
            self.price_callbacks[symbol].remove(callback)
            logger.debug(f"Unregistered price callback for {symbol}")

    async def disconnect_user(self, user_id: int):
        """Disconnect a user from WebSocket."""
        if user_id in self.user_connections:
            logger.info(f"Disconnecting user {user_id} from WebSocket")
            try:
                # Cancel all tasks associated with this user
                connection_data = self.user_connections[user_id]

                # Ping tasks больше не используются
                if user_id in self.ping_tasks:
                    logger.debug(f"Removing ping task reference for user {user_id}")
                    del self.ping_tasks[user_id]

                # Cancel keep alive task and other tasks
                if 'tasks' in connection_data:
                    for task in connection_data['tasks']:
                        try:
                            if not task.done() and not task.cancelled():
                                task.cancel()
                                # Ждем немного для завершения отмены
                                try:
                                    await asyncio.wait_for(asyncio.shield(task), timeout=0.5)
                                except (asyncio.TimeoutError, asyncio.CancelledError):
                                    pass
                        except Exception as e:
                            logger.error(f"Error cancelling task for user {user_id}: {e}")

                # Ensure WebSocket is closed
                if 'ws' in connection_data and not connection_data['ws'].closed:
                    try:
                        await connection_data['ws'].close()
                    except Exception as e:
                        logger.error(f"Error closing WebSocket for user {user_id}: {e}")

                # Ensure session is closed
                if 'session' in connection_data and not connection_data['session'].closed:
                    try:
                        await connection_data['session'].close()
                    except Exception as e:
                        logger.error(f"Error closing session for user {user_id}: {e}")

                # Delete listen key
                listen_key = connection_data.get('listen_key')
                if listen_key:
                    try:
                        user = await User.objects.aget(telegram_id=user_id)
                        if user.api_key and user.api_secret:
                            endpoint = "/api/v3/userDataStream"
                            url = f"{self.REST_API_URL}{endpoint}"

                            # Generate timestamp and signature for authentication
                            timestamp = int(time.time() * 1000)
                            query_string = f"timestamp={timestamp}&listenKey={listen_key}"
                            signature = hmac.new(
                                user.api_secret.encode(),
                                query_string.encode(),
                                hashlib.sha256
                            ).hexdigest()

                            headers = {
                                "X-MEXC-APIKEY": user.api_key,
                                "Content-Type": "application/json"
                            }

                            # Add timestamp and signature to the URL
                            request_url = f"{url}?{query_string}&signature={signature}"

                            async with aiohttp.ClientSession() as session:
                                await session.delete(request_url, headers=headers)
                    except Exception as e:
                        logger.error(f"Error deleting listen key for user {user_id}: {e}")

                # Finally, remove from user_connections
                del self.user_connections[user_id]
                logger.info(f"Disconnected user {user_id} from WebSocket")
            except Exception as e:
                logger.error(f"Error disconnecting user {user_id}: {e}")
                # Убеждаемся, что пользователь удален из соединений даже при ошибке
                if user_id in self.user_connections:
                    del self.user_connections[user_id]

    async def disconnect_market(self):
        """Disconnect from market data WebSocket."""
        if self.market_connection:
            try:
                # Сбрасываем флаги активности
                self.market_listener_active = False
                if hasattr(self, '_market_listener_started'):
                    delattr(self, '_market_listener_started')

                # Market ping task больше не используется
                if self.market_connection_task:
                    logger.debug("Clearing market connection task reference")
                    self.market_connection_task = None

                # Close WebSocket
                ws = self.market_connection.get('ws')
                if ws and not ws.closed:
                    try:
                        await ws.close()
                    except Exception as e:
                        logger.debug(f"Error closing market WebSocket: {e}")

                # Close session
                session = self.market_connection.get('session')
                if session and not session.closed:
                    try:
                        await session.close()
                    except Exception as e:
                        logger.debug(f"Error closing market session: {e}")

                self.market_connection = None
                logger.info("Disconnected from market data WebSocket")

            except Exception as e:
                logger.error(f"Error disconnecting market WebSocket: {e}")
                # Ensure cleanup even on error
                self.market_connection = None
                self.market_listener_active = False

    async def disconnect_all(self):
        """Disconnect all WebSocket connections."""
        self.is_shutting_down = True

        # Disconnect all user connections
        for user_id in list(self.user_connections.keys()):
            await self.disconnect_user(user_id)

        # Disconnect market connection
        await self.disconnect_market()

        logger.info("All WebSocket connections closed")

    async def connect_valid_users(self):
        """Connect all users with valid API keys."""
        from asgiref.sync import sync_to_async
        from django.db.models import Q

        # Get all users with API keys
        users = await sync_to_async(list)(User.objects.exclude(
            Q(api_key__isnull=True) |
            Q(api_key='') |
            Q(api_secret__isnull=True) |
            Q(api_secret='')
        ))

        logger.info(f"Found {len(users)} users with API keys")

        # Connect each user
        for user in users:
            await self.connect_user_data_stream(user.telegram_id)

    async def subscribe_user_orders(self, user_id: int, symbol: str = None):
        """
        Подписка на обновления ордеров пользователя.
        """
        if user_id not in self.user_connections:
            logger.warning(f"Невозможно подписаться: нет соединения для пользователя {user_id}")
            return False

        try:
            ws = self.user_connections[user_id]['ws']

            # Для пользовательских данных через listenKey
            # не нужно указывать конкретный символ - сервер сам
            # будет отправлять все обновления ордеров пользователя
            params = [
                "spot@private.orders.v3.api.pb",     # все ордера пользователя
                "spot@private.account.v3.api.pb"     # данные аккаунта
            ]

            # Отправляем запрос на подписку
            subscription_msg = {
                "method": "SUBSCRIPTION",
                "params": params,
                "id": int(time.time() * 1000)  # уникальный ID для запроса
            }

            await ws.send_str(json.dumps(subscription_msg))
            logger.info(f"Отправлен запрос на подписку для пользователя {user_id}: {params}")

            # Сохраняем информацию о подписке
            if 'subscriptions' not in self.user_connections[user_id]:
                self.user_connections[user_id]['subscriptions'] = []

            self.user_connections[user_id]['subscriptions'].extend(params)

            return True
        except Exception as e:
            logger.error(f"Ошибка при подписке на обновления ордеров пользователя {user_id}: {e}")
            return False

    async def monitor_connections(self):
        """Monitor and clean up stale connections."""
        logger.info("Starting connection monitor")
        market_failure_count = 0
        max_failures = 5

        while not self.is_shutting_down:
            try:
                current_time = time.time()

                # Проверяем market соединение
                if self.market_connection:
                    market_created = self.market_connection.get('created_at', 0)

                    # Проверяем, не закрыто ли соединение
                    ws = self.market_connection.get('ws')
                    if ws and ws.closed:
                        logger.warning("Market WebSocket is closed, reconnecting...")
                        await self.disconnect_market()
                        await asyncio.sleep(2)

                        if market_failure_count < max_failures:
                            success = await self.connect_market_data()
                            if success:
                                market_failure_count = 0
                            else:
                                market_failure_count += 1
                        else:
                            logger.error("Market WebSocket failed too many times, waiting longer...")
                            await asyncio.sleep(60)
                            market_failure_count = 0

                    # Проверяем возраст соединения (30 минут)
                    elif current_time - market_created > 1800:
                        logger.info("Market connection is stale, reconnecting...")
                        await self.disconnect_market()
                        await asyncio.sleep(2)
                        await self.connect_market_data()

                elif self.market_subscriptions:
                    # Если есть подписки, но нет соединения - пробуем переподключиться
                    logger.info("No market connection but have subscriptions, reconnecting...")
                    if market_failure_count < max_failures:
                        success = await self.connect_market_data()
                        if success:
                            market_failure_count = 0
                        else:
                            market_failure_count += 1
                    else:
                        await asyncio.sleep(60)
                        market_failure_count = 0

                # Проверяем пользовательские соединения (менее агрессивно)
                for user_id in list(self.user_connections.keys()):
                    connection_data = self.user_connections[user_id]
                    created_at = connection_data.get('created_at', 0)

                    # Проверяем только очень старые соединения (2 часа)
                    if current_time - created_at > 7200:  # 2 hours
                        logger.info(f"Connection for user {user_id} is very stale, reconnecting...")
                        await self.disconnect_user(user_id)
                        await asyncio.sleep(1)
                        await self.connect_user_data_stream(user_id)

                # Автоматическая очистка сессий каждые 2 минуты
                if int(current_time) % 120 == 0:  # Каждые 2 минуты
                    cleanup_count = await self.force_cleanup_sessions()
                    if cleanup_count > 0:
                        logger.info(f"Automatic cleanup removed {cleanup_count} stale sessions")

                # Ждем 30 секунд перед следующей проверкой (более частые проверки)
                await asyncio.sleep(30)

            except Exception as e:
                logger.error(f"Error in connection monitor: {e}")
                await asyncio.sleep(30)

    async def get_connection_stats(self):
        """Get statistics about current connections."""
        stats = {
            'user_connections': len(self.user_connections),
            'market_connection': self.market_connection is not None,
            'ping_tasks': len(self.ping_tasks),
            'reconnecting_users': len(self.reconnecting_users)
        }

        # Подсчитываем активные сессии
        session_count = 0
        closed_sessions = 0

        for connection_data in self.user_connections.values():
            if 'session' in connection_data:
                if connection_data['session'].closed:
                    closed_sessions += 1
                else:
                    session_count += 1

        if self.market_connection and 'session' in self.market_connection:
            if self.market_connection['session'].closed:
                closed_sessions += 1
            else:
                session_count += 1

        stats['active_sessions'] = session_count
        stats['closed_sessions'] = closed_sessions
        stats['total_market_subscriptions'] = len(self.market_subscriptions)
        stats['total_bookticker_subscriptions'] = len(self.bookticker_subscriptions)

        return stats

    async def force_cleanup_sessions(self):
        """Force cleanup all sessions to prevent resource leaks."""
        logger.info("Starting force cleanup of all sessions")
        cleanup_count = 0

        # Cleanup user sessions - более агрессивно
        for user_id in list(self.user_connections.keys()):
            try:
                connection_data = self.user_connections[user_id]
                session = connection_data.get('session')
                ws = connection_data.get('ws')

                # Чистим если сессия закрыта ИЛИ WebSocket закрыт
                if (session and session.closed) or (ws and ws.closed):
                    logger.info(f"Cleaning up session for user {user_id} (session_closed={session.closed if session else 'None'}, ws_closed={ws.closed if ws else 'None'})")
                    await self.disconnect_user(user_id)
                    cleanup_count += 1
            except Exception as e:
                logger.error(f"Error cleaning up user {user_id} session: {e}")

        # Cleanup market session if closed
        if self.market_connection:
            session = self.market_connection.get('session')
            ws = self.market_connection.get('ws')

            if (session and session.closed) or (ws and ws.closed):
                logger.info(f"Cleaning up market session (session_closed={session.closed if session else 'None'}, ws_closed={ws.closed if ws else 'None'})")
                await self.disconnect_market()
                cleanup_count += 1

        logger.info(f"Force cleanup completed, cleaned {cleanup_count} sessions")
        return cleanup_count

    async def emergency_session_cleanup(self):
        """Экстренная очистка всех сессий - принудительно закрываем все."""
        logger.warning("Starting EMERGENCY session cleanup")
        cleanup_count = 0

        # Принудительно отключаем всех пользователей
        user_ids = list(self.user_connections.keys())
        for user_id in user_ids:
            try:
                await self.disconnect_user(user_id)
                cleanup_count += 1
                logger.info(f"Force disconnected user {user_id}")
            except Exception as e:
                logger.error(f"Error force disconnecting user {user_id}: {e}")

        # Принудительно отключаем market
        if self.market_connection:
            try:
                await self.disconnect_market()
                cleanup_count += 1
                logger.info("Force disconnected market connection")
            except Exception as e:
                logger.error(f"Error force disconnecting market: {e}")

        # Сбрасываем все внутренние состояния
        self.user_connections.clear()
        self.ping_tasks.clear()
        self.reconnecting_users.clear()
        self.market_connection = None
        self.market_listener_active = False

        logger.warning(f"Emergency cleanup completed, cleaned {cleanup_count} connections")
        return cleanup_count

    async def health_check(self):
        """Perform health check on all connections."""
        health_stats = {
            'healthy_user_connections': 0,
            'unhealthy_user_connections': 0,
            'market_connection_healthy': False,
            'total_sessions': 0,
            'issues': []
        }

        # Check user connections
        for user_id, connection_data in self.user_connections.items():
            ws = connection_data.get('ws')
            session = connection_data.get('session')

            if ws and not ws.closed and session and not session.closed:
                health_stats['healthy_user_connections'] += 1
            else:
                health_stats['unhealthy_user_connections'] += 1
                health_stats['issues'].append(f"User {user_id} has unhealthy connection")

            if session:
                health_stats['total_sessions'] += 1

        # Check market connection
        if self.market_connection:
            ws = self.market_connection.get('ws')
            session = self.market_connection.get('session')

            if ws and not ws.closed and session and not session.closed:
                health_stats['market_connection_healthy'] = True
            else:
                health_stats['issues'].append("Market connection is unhealthy")

            if session:
                health_stats['total_sessions'] += 1

        return health_stats


# Create a singleton instance that will be imported and used throughout the application
websocket_manager = MexcWebSocketManager()
