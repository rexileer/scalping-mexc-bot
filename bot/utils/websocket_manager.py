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


class MexcWebSocketManager:
    """Class to manage WebSocket connections to MEXC exchange."""

    BASE_URL = "wss://wbs.mexc.com/ws"
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
        
        # Новые поля для отслеживания роста/падения цены
        self.price_history: Dict[str, List[float]] = {}  # {symbol: [prices]}
        self.price_timestamps: Dict[str, List[float]] = {}  # {symbol: [timestamps]}
        self.is_rise: Dict[str, bool] = {}  # {symbol: True/False} - текущее направление цены
        self.last_price_change: Dict[str, float] = {}  # {symbol: timestamp} - время последнего изменения направления
        self.max_history_size = 100  # Максимальное количество цен в истории для каждого символа

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
        while (not self.is_shutting_down and
               ((user_id is not None and user_id in self.user_connections) or
                (user_id is None and self.market_connection is not None))):
            try:
                await self.send_ping(ws)
                await asyncio.sleep(20)  # Send ping every 20 seconds
            except Exception as e:
                logger.error(f"Error in ping loop: {e}")
                break

    async def handle_market_message(self, message: dict):
        """Handle incoming market data messages."""
        try:
            # Импортируем handlers внутри метода
            from bot.utils.websocket_handlers import handle_price_update, handle_bookticker_update

            # Check the channel to determine message type
            channel = message.get('c', '')
            symbol = message.get('s')

            # Убираем дублирование логов - не логируем каждое сообщение

            if isinstance(message, dict) and symbol:
                # Handle bookTicker updates
                if 'bookTicker' in channel:
                    # BookTicker message format: {"c":"spot@public.bookTicker.v3.api@KASUSDC","d":{"A":"14.53","B":"103.81","a":"0.096287","b":"0.095972"},"s":"KASUSDC","t":1753001356734}
                    bookticker_data = message.get('d', {})
                    if bookticker_data:
                        # Используем правильные ключи из логов: a=ask, b=bid, A=ask_qty, B=bid_qty
                        bid_price = bookticker_data.get('b')  # bid price
                        ask_price = bookticker_data.get('a')  # ask price
                        bid_qty = bookticker_data.get('B')    # bid quantity
                        ask_qty = bookticker_data.get('A')    # ask quantity

                        if bid_price and ask_price:
                            # Store current bookTicker data
                            self.current_bookticker[symbol] = {
                                'bid_price': bid_price,
                                'ask_price': ask_price,
                                'bid_qty': bid_qty,
                                'ask_qty': ask_qty,
                                'timestamp': message.get('t', int(time.time() * 1000))
                            }

                            # logger.debug(f"[MarketWS] BookTicker update for {symbol}: bid={bid_price}, ask={ask_price}")

                            # Call bookTicker-specific handlers
                            await handle_bookticker_update(symbol, bid_price, ask_price, bid_qty, ask_qty)

                            # Call any registered bookTicker callbacks
                            if symbol in self.bookticker_callbacks:
                                logger.debug(f"[MarketWS] Found {len(self.bookticker_callbacks[symbol])} bookTicker callbacks for {symbol}")
                                for callback in self.bookticker_callbacks[symbol]:
                                    try:
                                        await callback(symbol, bid_price, ask_price, bid_qty, ask_qty)
                                    except Exception as e:
                                        logger.error(f"[MarketWS] Error in bookTicker callback for {symbol}: {e}", exc_info=True)
                            else:
                                logger.debug(f"[MarketWS] No bookTicker callbacks registered for symbol {symbol}")

                            # Обновляем логику определения роста/падения цены
                            await self._update_price_direction(symbol, float(bid_price), float(ask_price))

                # Handle deals (price updates)
                elif 'deals' in channel:
                    # Deals message format: {"c":"spot@public.deals.v3.api@KASUSDC","d":{"deals":[{"p":"0.098348","v":"324.94","S":1,"t":1753015604473}],"e":"spot@public.deals.v3.api"},"s":"KASUSDC"}
                    deals_data = message.get('d', {}).get('deals', [])
                    if deals_data and len(deals_data) > 0:
                        # Берем цену из первой сделки в массиве
                        price_data = deals_data[0].get('p')
                        if price_data:
                            logger.debug(f"[MarketWS] Price update for {symbol}: {price_data}")

                            # Call any registered price callbacks
                            if symbol in self.price_callbacks:
                                logger.debug(f"[MarketWS] Found {len(self.price_callbacks[symbol])} callbacks for {symbol}")
                                for callback in self.price_callbacks[symbol]:
                                    try:
                                        logger.debug(f"[MarketWS] Calling callback {callback.__name__} for {symbol} with price {price_data}")
                                        await callback(symbol, price_data)
                                    except Exception as e:
                                        logger.error(f"[MarketWS] Error in price callback for {symbol} ({callback.__name__}): {e}", exc_info=True)
                            else:
                                logger.debug(f"[MarketWS] No callbacks registered for symbol {symbol}")
                        else:
                            logger.warning(f"[MarketWS] Could not extract price from deals array for symbol {symbol}: {message}")
                    else:
                        logger.warning(f"[MarketWS] Could not extract deals array for symbol {symbol}: {message}")

            # Handle subscription responses and other service messages
            if message.get("method") == "SUBSCRIPTION" and message.get("code") == 0:
                logger.info(f"[MarketWS] Subscription successful response: {message}")
            elif message.get("code") != 0 and message.get("msg"):
                logger.error(f"[MarketWS] Received error message response from MEXC: {message}")
            elif not symbol:
                logger.debug(f"[MarketWS] Received non-symbol or unrecognized market message: {message}")

        except Exception as e:
            logger.error(f"Error handling market message: {e}")

    async def _update_price_direction(self, symbol: str, bid_price: float, ask_price: float):
        """
        Обновляет направление цены (рост/падение) на основе bookTicker данных.
        Использует среднюю цену (bid + ask) / 2 для определения направления.
        """
        try:
            current_time = time.time()
            mid_price = (bid_price + ask_price) / 2
            
            # Инициализируем историю цен, если её нет
            if symbol not in self.price_history:
                self.price_history[symbol] = []
                self.price_timestamps[symbol] = []
                self.is_rise[symbol] = False
                self.last_price_change[symbol] = current_time
            
            # Добавляем новую цену в историю
            self.price_history[symbol].append(mid_price)
            self.price_timestamps[symbol].append(current_time)
            
            # Ограничиваем размер истории
            if len(self.price_history[symbol]) > self.max_history_size:
                self.price_history[symbol] = self.price_history[symbol][-self.max_history_size:]
                self.price_timestamps[symbol] = self.price_timestamps[symbol][-self.max_history_size:]
            
            # Определяем направление цены (нужно минимум 2 точки)
            if len(self.price_history[symbol]) >= 2:
                current_price = self.price_history[symbol][-1]
                previous_price = self.price_history[symbol][-2]
                
                # Определяем новое направление
                new_is_rise = current_price > previous_price
                
                # Если направление изменилось, обновляем время последнего изменения
                if new_is_rise != self.is_rise[symbol]:
                    self.last_price_change[symbol] = current_time
                    logger.debug(f"[PriceDirection] {symbol}: Direction changed from {'rise' if self.is_rise[symbol] else 'fall'} to {'rise' if new_is_rise else 'fall'}. Price: {previous_price:.6f} -> {current_price:.6f}")
                
                self.is_rise[symbol] = new_is_rise
                
                logger.debug(f"[PriceDirection] {symbol}: Current direction = {'rise' if new_is_rise else 'fall'}, Price = {current_price:.6f}")
            
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
        if symbol not in self.is_rise:
            return {
                'is_rise': False,
                'last_change_time': 0,
                'current_price': 0,
                'price_history': []
            }
        
        current_price = 0
        if self.price_history.get(symbol):
            current_price = self.price_history[symbol][-1]
        
        return {
            'is_rise': self.is_rise[symbol],
            'last_change_time': self.last_price_change.get(symbol, 0),
            'current_price': current_price,
            'price_history': self.price_history.get(symbol, [])
        }

    async def connect_user_data_stream(self, user_id: int) -> bool:
        """Connect to user data stream for a specific user."""
        # Если пользователь уже в процессе переподключения, просто ждем и возвращаем True
        if user_id in self.reconnecting_users:
            logger.info(f"User {user_id} is already in reconnection process. Skipping.")
            await asyncio.sleep(0.5)  # Небольшая задержка для завершения текущего процесса переподключения
            return True

        # Добавляем пользователя в список переподключающихся
        self.reconnecting_users.add(user_id)

        try:
            # Сначала отключаем существующее соединение
            if user_id in self.user_connections:
                await self.disconnect_user(user_id)
                # Небольшая задержка перед повторным подключением
                await asyncio.sleep(1)

            user = await User.objects.aget(telegram_id=user_id)

            if not user.api_key or not user.api_secret:
                logger.warning(f"User {user_id} missing API keys")
                self.reconnecting_users.remove(user_id)
                return False

            # Get a listen key for the user
            success, error_message, listen_key = await self.get_listen_key(user.api_key, user.api_secret)
            if not success:
                logger.error(f"Error connecting user {user_id} to WebSocket: {error_message}")
                self.reconnecting_users.remove(user_id)
                return False

            ws_url = f"{self.BASE_URL}?listenKey={listen_key}"

            # Create WebSocket connection
            session = aiohttp.ClientSession()
            try:
                ws = await session.ws_connect(ws_url)
            except Exception as e:
                await session.close()
                logger.error(f"Error connecting to WebSocket for user {user_id}: {e}")
                self.reconnecting_users.remove(user_id)
                return False

            # Store connection info
            self.user_connections[user_id] = {
                'ws': ws,
                'session': session,
                'listen_key': listen_key,
                'tasks': []  # Список для хранения задач
            }

            # Start ping loop to keep connection alive
            ping_task = asyncio.create_task(self.ping_loop(ws, user_id))
            self.ping_tasks[user_id] = ping_task
            self.user_connections[user_id]['tasks'].append(ping_task)

            # Start task to keep listen key alive
            keep_alive_task = asyncio.create_task(
                self.keep_listen_key_alive(user_id, user.api_key, user.api_secret)
            )
            self.user_connections[user_id]['keep_alive_task'] = keep_alive_task
            self.user_connections[user_id]['tasks'].append(keep_alive_task)

            # Start listening for messages
            listen_task = asyncio.create_task(self._listen_user_messages(user_id))
            self.user_connections[user_id]['tasks'].append(listen_task)

            # После успешного подключения подписываемся на ордера
            await self.subscribe_user_orders(user_id)

            logger.info(f"Connected user {user_id} to WebSocket and subscribed to orders")
            self.reconnecting_users.remove(user_id)
            return True
        except Exception as e:
            logger.error(f"Error connecting user {user_id} to WebSocket: {e}")
            if user_id in self.reconnecting_users:
                self.reconnecting_users.remove(user_id)
            return False

    async def _listen_user_messages(self, user_id: int):
        """Listen for messages from user data stream."""
        if user_id not in self.user_connections:
            return

        ws = self.user_connections[user_id]['ws']

        try:
            # Импортируем обработчики внутри метода
            from bot.utils.websocket_handlers import update_order_status, handle_order_update, handle_account_update

            while not self.is_shutting_down and user_id in self.user_connections:
                try:
                    msg = await ws.receive(timeout=30)
                except asyncio.TimeoutError:
                    # Проверяем соединение с помощью пинга
                    if ws.closed:
                        logger.warning(f"WebSocket for user {user_id} closed during receive timeout.")
                        break
                    try:
                        await self.send_ping(ws)
                        continue
                    except Exception:
                        logger.warning(f"Failed to send ping for user {user_id}, connection may be broken.")
                        break

                if msg.type == aiohttp.WSMsgType.TEXT:
                    data = json.loads(msg.data)

                    # Проверка сервисных сообщений
                    if 'id' in data and 'code' in data:
                        # Понижаем уровень логирования
                        logger.debug(f"Сервисное сообщение для {user_id}: {data}")
                        continue

                    # Проверка PING/PONG
                    if 'pong' in data:
                        logger.debug(f"Received PONG from server for user {user_id}")
                        continue

                    if 'ping' in data:
                        pong_msg = {'pong': data['ping']}
                        await ws.send_str(json.dumps(pong_msg))
                        logger.debug(f"Sent PONG in response to server PING for user {user_id}")
                        continue

                    # Обработка событий с данными
                    channel = data.get('c')

                    if channel == "spot@private.orders.v3.api":
                        # Обрабатываем обновления ордера
                        order_data = data.get('d', {})
                        symbol = data.get('s')
                        order_id = order_data.get('i')
                        status_code = order_data.get('s')

                        # Карта статусов MEXC -> наша БД
                        status_map = {
                            1: "NEW",           # 1 - новый
                            2: "FILLED",        # 2 - исполнен
                            3: "PARTIALLY_FILLED", # 3 - частично исполнен
                            4: "CANCELED",      # 4 - отменен
                            5: "REJECTED"       # 5 - отклонен
                        }
                        status = status_map.get(status_code, "UNKNOWN")

                        logger.info(f"Обновление ордера {order_id} для пользователя {user_id}: {symbol} - {status}")

                        # Обновляем статус в БД
                        try:
                            await update_order_status(order_id, symbol, status)
                        except Exception as e:
                            logger.error(f"Ошибка обновления статуса ордера: {e}")

                    elif channel == "spot@private.account.v3.api":
                        # Обрабатываем изменения в аккаунте
                        account_data = data.get('d', {})
                        asset = account_data.get('a')  # Актив (валюта)
                        free = account_data.get('f')   # Доступный баланс
                        locked = account_data.get('l') # Заблокированный баланс

                        logger.info(f"Обновление баланса для {user_id}: {asset} - свободно: {free}, заблокировано: {locked}")
                    else:
                        logger.debug(f"Неизвестный канал для {user_id}: {channel}, данные: {json.dumps(data)}")

                elif msg.type == aiohttp.WSMsgType.CLOSED:
                    logger.warning(f"WebSocket for user {user_id} closed")
                    break

                elif msg.type == aiohttp.WSMsgType.ERROR:
                    logger.error(f"WebSocket error for user {user_id}: {ws.exception()}")
                    break
        except (asyncio.CancelledError, GeneratorExit):
            logger.info(f"WebSocket listener task cancelled for user {user_id}")
        except json.JSONDecodeError as e:
            logger.error(f"JSON decode error in WebSocket for user {user_id}: {e}")
        except Exception as e:
            logger.error(f"Error in user WebSocket for {user_id}: {e}")
        finally:
            # Connection is closed, try to reconnect after a delay if we're not shutting down
            # and the user is not already being reconnected
            if not self.is_shutting_down and user_id not in self.reconnecting_users:
                logger.info(f"Reconnecting user {user_id} WebSocket in {self.reconnect_delay} seconds")
                await asyncio.sleep(self.reconnect_delay)
                self.reconnect_delay = min(self.reconnect_delay * 2, 60)  # Exponential backoff

                # Если пользователь еще в соединениях, пробуем переподключить
                if user_id in self.user_connections:
                    asyncio.create_task(self.connect_user_data_stream(user_id))

    async def connect_market_data(self, symbols: List[str] = None):
        """
        Connect to market data stream and subscribe to specified symbols.
        If no symbols are provided, will use existing subscriptions.
        """
        try:
            session = aiohttp.ClientSession()
            ws = await session.ws_connect(self.BASE_URL)

            self.market_connection = {
                'ws': ws,
                'session': session
            }

            # Start ping loop
            self.market_connection_task = asyncio.create_task(self.ping_loop(ws))

            # Subscribe to symbols if provided
            if symbols:
                await self.subscribe_market_data(symbols)
                # Также подписываемся на bookTicker для тех же символов
                await self.subscribe_bookticker_data(symbols)
            elif self.market_subscriptions:
                # Reuse existing subscriptions
                await self.subscribe_market_data(self.market_subscriptions)
                await self.subscribe_bookticker_data(self.bookticker_subscriptions)

            # Start listening for messages
            asyncio.create_task(self._listen_market_messages())

            logger.info("Connected to market data WebSocket")
            return True
        except Exception as e:
            logger.error(f"Error connecting to market data WebSocket: {e}")
            return False

    async def subscribe_market_data(self, symbols: List[str]):
        """Subscribe to market data for specific symbols."""
        if not self.market_connection:
            logger.error("Market connection not established")
            return False

        try:
            ws = self.market_connection['ws']

            # Format subscription parameters for each symbol
            # According to MEXC documentation, the format for deals is:
            # spot@public.deals.v3.api@BTCUSDT
            params = [f"spot@public.deals.v3.api@{symbol.upper()}" for symbol in symbols]

            # Send subscription request
            subscription_msg = {
                "method": "SUBSCRIPTION",
                "params": params
            }

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
            params = [f"spot@public.bookTicker.v3.api@{symbol.upper()}" for symbol in symbols]

            # Send subscription request
            subscription_msg = {
                "method": "SUBSCRIPTION",
                "params": params
            }

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
        if not self.market_connection or not self.market_connection.get('ws'):
            logger.error("[MarketWS] Market connection or WebSocket not established for listening.")
            return

        ws = self.market_connection['ws']
        logger.info(f"[MarketWS] Starting to listen for market messages on: {ws}")

        try:
            while not self.is_shutting_down and self.market_connection and not ws.closed:
                try:
                    msg = await ws.receive(timeout=30) # Добавляем таймаут для периодической проверки ws.closed
                except asyncio.TimeoutError:
                    logger.debug(f"[MarketWS] Timeout receiving message, checking connection.")
                    if ws.closed:
                        logger.warning("[MarketWS] WebSocket closed during receive timeout.")
                        break
                    # Если не закрыто, отправляем пинг для поддержания активности, если необходимо
                    await self.send_ping(ws)
                    continue

                if msg:
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        logger.debug(f"[MarketWS] Received TEXT message: {msg.data[:200]}...") # Уменьшаем логирование
                        try:
                            data = json.loads(msg.data)
                        except json.JSONDecodeError as e:
                            logger.error(f"[MarketWS] JSONDecodeError: {e} for data: {msg.data[:500]}")
                            continue

                        # Check for PONG response or other control messages
                        if 'pong' in data:
                            logger.debug(f"[MarketWS] Received PONG: {data}")
                            continue
                        if 'ping' in data: # Сервер может прислать ping
                            logger.debug(f"[MarketWS] Received PING from server: {data}, sending PONG.")
                            try:
                                await ws.send_json({"pong": data['ping']})
                            except Exception as e:
                                logger.error(f"[MarketWS] Error sending PONG: {e}")
                            continue
                        # Проверяем ответ на подписку и другие ошибки тут, до передачи в handle_market_message
                        if data.get("method") == "SUBSCRIPTION" and data.get("code") == 0:
                            logger.info(f"[MarketWS] Subscription successful in _listen_market_messages: {data}")
                            continue # Это сообщение об успешной подписке, не передаем его в handle_market_message
                        if data.get("code") != 0 and data.get("msg"):
                             logger.error(f"[MarketWS] Received error message from MEXC in _listen_market_messages: {data}")
                             continue # Это сообщение об ошибке, не передаем его в handle_market_message

                        # Process market data
                        logger.debug(f"[MarketWS] Processing market data: {data}")  # Уменьшаем логирование
                        await self.handle_market_message(data)

                    elif msg.type == aiohttp.WSMsgType.CLOSED:
                        logger.warning(f"[MarketWS] WebSocket CLOSED message received. Reason: {ws.close_code}")
                        break

                    elif msg.type == aiohttp.WSMsgType.ERROR:
                        logger.error(f"[MarketWS] WebSocket ERROR message received: {ws.exception()}")
                        break
                    elif msg.type == aiohttp.WSMsgType.CLOSING:
                        logger.info("[MarketWS] WebSocket CLOSING message received.")
                        break # Начинаем процесс закрытия
                    else:
                        logger.debug(f"[MarketWS] Received other message type: {msg.type}")
                else:
                    # msg is None, может произойти если соединение закрывается
                    logger.warning("[MarketWS] Received None message, WebSocket might be closing.")
                    if ws.closed:
                         break # Выходим если сокет уже закрыт
                    await asyncio.sleep(0.1) # Небольшая пауза
        except Exception as e:
            logger.error(f"[MarketWS] Error in _listen_market_messages: {e}", exc_info=True)
        finally:
            logger.warning("[MarketWS] Exited _listen_market_messages loop.")
            # Connection is closed, try to reconnect after a delay
            if not self.is_shutting_down:
                logger.info(f"Reconnecting market WebSocket in {self.reconnect_delay} seconds")
                await asyncio.sleep(self.reconnect_delay)
                self.reconnect_delay = min(self.reconnect_delay * 2, 60)  # Exponential backoff
                await self.disconnect_market()
                await self.connect_market_data()

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

                # Cancel ping task
                if user_id in self.ping_tasks:
                    try:
                        self.ping_tasks[user_id].cancel()
                    except Exception as e:
                        logger.error(f"Error cancelling ping task for user {user_id}: {e}")
                    finally:
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

    async def disconnect_market(self):
        """Disconnect from market data WebSocket."""
        if self.market_connection:
            try:
                if self.market_connection_task:
                    self.market_connection_task.cancel()
                    self.market_connection_task = None

                await self.market_connection['ws'].close()
                await self.market_connection['session'].close()
                self.market_connection = None
                logger.info("Disconnected from market data WebSocket")
            except Exception as e:
                logger.error(f"Error disconnecting market WebSocket: {e}")

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
                "spot@private.orders.v3.api",     # все ордера пользователя
                "spot@private.account.v3.api"     # данные аккаунта
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


# Create a singleton instance that will be imported and used throughout the application
websocket_manager = MexcWebSocketManager()
