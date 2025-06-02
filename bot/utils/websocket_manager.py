import asyncio
import json
import time
import logging
import aiohttp
from typing import Dict, List, Optional, Callable, Any
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
        self.market_connection_task = None
        self.ping_tasks: Dict[int, asyncio.Task] = {}
        self.price_callbacks: Dict[str, List[Callable]] = {}  # {symbol: [callbacks]}
        self.reconnect_delay = 1  # Initial reconnect delay in seconds
        self.is_shutting_down = False
    
    async def get_listen_key(self, api_key: str, api_secret: str) -> str:
        """Get a listen key for user data streams."""
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
        
        async with aiohttp.ClientSession() as session:
            async with session.post(request_url, headers=headers) as response:
                if response.status != 200:
                    error_text = await response.text()
                    logger.error(f"Failed to get listen key: {error_text}")
                    raise Exception(f"Failed to get listen key: {response.status}")
                
                data = await response.json()
                return data.get("listenKey")
    
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
            # Импортируем handle_price_update внутри метода
            from bot.utils.websocket_handlers import handle_price_update
            
            # In MEXC's WebSocket API, the deal message structure is different
            # Check if it's a deal update message
            if isinstance(message, dict) and 's' in message and 'c' in message: # 'c' здесь это канал, а не цена
                # Более точная проверка на сообщение о сделках (deals)
                # Сообщение о сделках имеет структуру типа: {"c":"spot@public.deals.v3.api@KASUSDC","d":{"deals":[{"p":"0.087565","q":"553.6","T":1,"t":1701880076719,"v":"48.4805804"}]},"s":"KASUSDC","t":1701880076719}
                # Или для одиночной сделки: {'e': 'spot@public.deals.v3.api@BTCUSDT', 's': 'BTCUSDT', 't': 1234567890, 'p': '66123.45', 'q': '0.01234', 'c': '1'}
                # Новый формат от MEXC (из их документации) для канала spot@public.deals.v3.api@<symbol>
                # присылает данные в ключе "d" -> "deals" -> массив объектов, где каждый объект это сделка с полями "p" (цена), "q" (количество) и т.д.
                # или напрямую поля 's' (symbol), 'p' (price) в корне объекта, если это одиночная сделка из другого типа подписки или формата.

                logger.debug(f"[MarketWS] Handling message: {message}")

                symbol = message.get('s') # Символ есть в корне
                price_data = None

                if 'd' in message and 'deals' in message['d'] and message['d']['deals']:
                    # Это массив сделок, берем цену из последней сделки в массиве
                    latest_deal = message['d']['deals'][-1]
                    price_data = latest_deal.get('p')
                    logger.debug(f"[MarketWS] Extracted price {price_data} for {symbol} from deals array: {latest_deal}")
                elif 'p' in message: 
                    # Это одиночная сделка с ценой в корне (старый или альтернативный формат)
                    price_data = message.get('p')
                    logger.debug(f"[MarketWS] Extracted price {price_data} for {symbol} from root price field.")
                else:
                    logger.warning(f"[MarketWS] Could not extract price from message for symbol {symbol}: {message}")

                if symbol and price_data:
                    # Process with the general handler (если он вам нужен для других целей)
                    # await handle_price_update(symbol, price_data) # Закомментировано, т.к. основная логика в autobuy
                    
                    logger.info(f"[MarketWS] Price update for {symbol}: {price_data}")

                    # Call any registered callbacks
                    if symbol in self.price_callbacks:
                        logger.debug(f"[MarketWS] Found {len(self.price_callbacks[symbol])} callbacks for {symbol}")
                        for callback in self.price_callbacks[symbol]:
                            try:
                                logger.debug(f"[MarketWS] Calling callback {callback.__name__} for {symbol} with price {price_data}")
                                await callback(symbol, price_data) # Передаем symbol и price_data
                            except Exception as e:
                                logger.error(f"[MarketWS] Error in price callback for {symbol} ({callback.__name__}): {e}", exc_info=True)
                    else:
                        logger.debug(f"[MarketWS] No callbacks registered for symbol {symbol}. Callbacks: {self.price_callbacks.keys()}")
                elif symbol:
                    logger.warning(f"[MarketWS] Symbol {symbol} found, but no price data in message: {message}")
            else:
                # Это может быть ответ на подписку или другое сервисное сообщение
                if message.get("method") == "SUBSCRIPTION" and message.get("code") == 0:
                    logger.info(f"[MarketWS] Subscription successful response: {message}")
                elif message.get("code") != 0 and message.get("msg"):
                    logger.error(f"[MarketWS] Received error message response from MEXC: {message}")
                else:
                    logger.debug(f"[MarketWS] Received non-deal or unrecognized market message: {message}")
        except Exception as e:
            logger.error(f"Error handling market message: {e}")
    
    async def connect_user_data_stream(self, user_id: int):
        """Connect to user data stream for a specific user."""
        try:
            user = await User.objects.aget(telegram_id=user_id)
            
            if not user.api_key or not user.api_secret:
                logger.warning(f"User {user_id} missing API keys")
                return False
            
            # Get a listen key for the user
            listen_key = await self.get_listen_key(user.api_key, user.api_secret)
            ws_url = f"{self.BASE_URL}?listenKey={listen_key}"
            
            # Create WebSocket connection
            session = aiohttp.ClientSession()
            ws = await session.ws_connect(ws_url)
            
            # Store connection info
            self.user_connections[user_id] = {
                'ws': ws,
                'session': session,
                'listen_key': listen_key
            }
            
            # Start ping loop to keep connection alive
            ping_task = asyncio.create_task(self.ping_loop(ws, user_id))
            self.ping_tasks[user_id] = ping_task
            
            # Start task to keep listen key alive
            keep_alive_task = asyncio.create_task(
                self.keep_listen_key_alive(user_id, user.api_key, user.api_secret)
            )
            self.user_connections[user_id]['keep_alive_task'] = keep_alive_task
            
            # Start listening for messages
            asyncio.create_task(self._listen_user_messages(user_id))
            
            # После успешного подключения подписываемся на ордера
            await self.subscribe_user_orders(user_id)
            
            logger.info(f"Connected user {user_id} to WebSocket and subscribed to orders")
            return True
        except Exception as e:
            logger.error(f"Error connecting user {user_id} to WebSocket: {e}")
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
                msg = await ws.receive()
                
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
        except Exception as e:
            logger.error(f"Error in user WebSocket for {user_id}: {e}")
        finally:
            # Connection is closed, try to reconnect after a delay
            if not self.is_shutting_down:
                logger.info(f"Reconnecting user {user_id} WebSocket in {self.reconnect_delay} seconds")
                await asyncio.sleep(self.reconnect_delay)
                self.reconnect_delay = min(self.reconnect_delay * 2, 60)  # Exponential backoff
                await self.disconnect_user(user_id)
                await self.connect_user_data_stream(user_id)
    
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
            elif self.market_subscriptions:
                # Reuse existing subscriptions
                await self.subscribe_market_data(self.market_subscriptions)
            
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
                    # await self.send_ping(ws) # Можно раскомментировать, если пинги из ping_loop не справляются
                    continue 

                if msg:
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        logger.debug(f"[MarketWS] Received TEXT message: {msg.data[:500]}") # Логируем часть сообщения
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
                        logger.debug(f"[MarketWS] Passing data to handle_market_message: {data}")
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
    
    async def disconnect_user(self, user_id: int):
        """Disconnect a user from WebSocket."""
        if user_id in self.user_connections:
            try:
                # Cancel ping task
                if user_id in self.ping_tasks:
                    self.ping_tasks[user_id].cancel()
                    del self.ping_tasks[user_id]
                
                # Cancel keep alive task
                if 'keep_alive_task' in self.user_connections[user_id]:
                    self.user_connections[user_id]['keep_alive_task'].cancel()
                
                # Close WebSocket
                await self.user_connections[user_id]['ws'].close()
                
                # Close session
                await self.user_connections[user_id]['session'].close()
                
                # Delete listen key
                listen_key = self.user_connections[user_id]['listen_key']
                user = await User.objects.aget(telegram_id=user_id)
                
                if user.api_key and user.api_secret and listen_key:
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