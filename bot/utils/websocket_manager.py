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
from bot.utils.websocket_handlers import handle_order_update, handle_account_update, handle_price_update


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
            # In MEXC's WebSocket API, the deal message structure is different
            # Check if it's a deal update message
            if isinstance(message, dict) and 's' in message and 'c' in message:
                # Example of deals stream: {'e': 'spot@public.deals.v3.api@BTCUSDT', 's': 'BTCUSDT', 't': 1234567890, 'p': '66123.45', 'q': '0.01234', 'c': '1'}
                # Extract symbol from subscription stream (remove the prefix)
                symbol = message.get('s')
                price = message.get('p')  # Price is in 'p', not 'c'
                
                if symbol and price:
                    # Process with the general handler
                    await handle_price_update(symbol, price)
                    
                    # Call any registered callbacks
                    if symbol in self.price_callbacks:
                        for callback in self.price_callbacks[symbol]:
                            try:
                                await callback(symbol, price)
                            except Exception as e:
                                logger.error(f"Error in price callback for {symbol}: {e}")
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
            
            logger.info(f"Connected user {user_id} to WebSocket")
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
            while not self.is_shutting_down and user_id in self.user_connections:
                msg = await ws.receive()
                
                if msg.type == aiohttp.WSMsgType.TEXT:
                    data = json.loads(msg.data)
                    
                    # Check for PONG response
                    if 'pong' in data:
                        # This is a pong response
                        continue
                    
                    # Check for PING response
                    if 'ping' in data:
                        # Ответить PONG на тот же WebSocket
                        pong_msg = {'pong': data['ping']}
                        await ws.send_str(json.dumps(pong_msg))
                        logger.debug(f"Отправлен PONG в ответ на PING от сервера")
                        continue
                    
                    # Process user-specific messages
                    event_type = data.get('e')
                    
                    if event_type == 'executionReport':
                        # Order update
                        await handle_order_update(user_id, data)
                    elif event_type == 'outboundAccountPosition':
                        # Account update
                        await handle_account_update(user_id, data)
                    else:
                        # Unknown event type
                        logger.debug(f"User {user_id} received unknown event: {event_type}")
                
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
        if not self.market_connection:
            return
        
        ws = self.market_connection['ws']
        
        try:
            while not self.is_shutting_down and self.market_connection:
                msg = await ws.receive()
                
                if msg.type == aiohttp.WSMsgType.TEXT:
                    data = json.loads(msg.data)
                    
                    # Check for PONG response
                    if 'pong' in data:
                        # This is a pong response
                        continue
                    
                    # Process market data
                    await self.handle_market_message(data)
                
                elif msg.type == aiohttp.WSMsgType.CLOSED:
                    logger.warning("Market WebSocket closed")
                    break
                
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    logger.error(f"Market WebSocket error: {ws.exception()}")
                    break
        except Exception as e:
            logger.error(f"Error in market WebSocket: {e}")
        finally:
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


# Create a singleton instance that will be imported and used throughout the application
websocket_manager = MexcWebSocketManager() 