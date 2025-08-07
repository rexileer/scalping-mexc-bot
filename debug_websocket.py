#!/usr/bin/env python3
"""
Debug script для диагностики WebSocket проблем с MEXC.

Использование:
python debug_websocket.py

Этот скрипт поможет понять почему MEXC отключает соединения через 30 секунд.
"""

import asyncio
import json
import time
import aiohttp
import logging

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class MEXCDebugClient:
    """Debug client для тестирования MEXC WebSocket соединений."""
    
    BASE_URL = "wss://wbs.mexc.com/ws"
    
    def __init__(self):
        self.connection_start = None
        self.last_message_time = None
        self.message_count = 0
        self.subscription_responses = []
        
    async def test_market_connection(self):
        """Тест market data соединения."""
        logger.info("Starting MEXC WebSocket connection test...")
        
        try:
            session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=120),  # 2 минуты timeout
                connector=aiohttp.TCPConnector(
                    enable_cleanup_closed=True
                )
            )
            
            ws = await session.ws_connect(
                self.BASE_URL,
                heartbeat=20,
                compress=False
            )
            
            self.connection_start = time.time()
            logger.info(f"✅ Connected to {self.BASE_URL}")
            
            # Подписываемся на KASUSDC
            subscription_msg = {
                "method": "SUBSCRIPTION",
                "params": [
                    "spot@public.deals.v3.api@KASUSDC",
                    "spot@public.bookTicker.v3.api@KASUSDC"
                ],
                "id": int(time.time() * 1000)
            }
            
            logger.info(f"📤 Sending subscription: {subscription_msg}")
            await ws.send_str(json.dumps(subscription_msg))
            
            # Слушаем сообщения
            await self._listen_messages(ws)
            
        except Exception as e:
            logger.error(f"❌ Connection test failed: {e}")
        finally:
            try:
                await ws.close()
                await session.close()
            except:
                pass
    
    async def _listen_messages(self, ws):
        """Слушаем сообщения от WebSocket."""
        logger.info("🎧 Starting to listen for messages...")
        
        try:
            while not ws.closed:
                try:
                    msg = await ws.receive(timeout=60)  # 1 минута timeout
                    
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        self.message_count += 1
                        self.last_message_time = time.time()
                        connection_age = self.last_message_time - self.connection_start
                        
                        data = json.loads(msg.data)
                        
                        # Логируем разные типы сообщений
                        if 'ping' in data:
                            logger.info(f"🏓 PING received at {connection_age:.1f}s: {data}")
                            # Отвечаем PONG
                            await ws.send_json({"pong": data['ping']})
                            logger.info(f"🏓 PONG sent")
                            
                        elif data.get('method') == 'SUBSCRIPTION':
                            self.subscription_responses.append(data)
                            if data.get('code') == 0:
                                logger.info(f"✅ Subscription successful at {connection_age:.1f}s: {data}")
                            else:
                                logger.error(f"❌ Subscription failed at {connection_age:.1f}s: {data}")
                                
                        elif 's' in data:  # Market data message
                            symbol = data.get('s')
                            channel = data.get('c', '')
                            logger.info(f"📊 Market data at {connection_age:.1f}s: {symbol} via {channel[:30]}...")
                            
                        else:
                            logger.info(f"📨 Other message at {connection_age:.1f}s: {str(data)[:100]}...")
                    
                    elif msg.type == aiohttp.WSMsgType.CLOSED:
                        connection_age = time.time() - self.connection_start
                        logger.warning(f"🔌 WebSocket closed at {connection_age:.1f}s. Close code: {ws.close_code}")
                        break
                        
                    elif msg.type == aiohttp.WSMsgType.ERROR:
                        connection_age = time.time() - self.connection_start
                        logger.error(f"💥 WebSocket error at {connection_age:.1f}s: {ws.exception()}")
                        break
                        
                    elif msg.type == aiohttp.WSMsgType.CLOSING:
                        connection_age = time.time() - self.connection_start
                        logger.info(f"🔄 WebSocket closing at {connection_age:.1f}s...")
                        # Ждем корректного закрытия
                        for i in range(50):
                            if ws.closed:
                                break
                            await asyncio.sleep(0.1)
                        break
                        
                except asyncio.TimeoutError:
                    connection_age = time.time() - self.connection_start
                    logger.warning(f"⏰ Timeout receiving message at {connection_age:.1f}s")
                    
                    # Проверяем, не закрыто ли соединение
                    if ws.closed:
                        logger.warning(f"🔌 WebSocket closed during timeout at {connection_age:.1f}s")
                        break
                        
                    # Отправляем ping для проверки соединения
                    try:
                        ping_msg = {"ping": int(time.time() * 1000)}
                        await ws.send_json(ping_msg)
                        logger.info(f"🏓 Manual PING sent at {connection_age:.1f}s")
                    except Exception as e:
                        logger.error(f"💥 Failed to send ping: {e}")
                        break
                        
        except Exception as e:
            connection_age = time.time() - self.connection_start if self.connection_start else 0
            logger.error(f"💥 Error in message listener at {connection_age:.1f}s: {e}")
        finally:
            self._print_summary()
    
    def _print_summary(self):
        """Печатаем сводку теста."""
        connection_age = time.time() - self.connection_start if self.connection_start else 0
        
        logger.info("=" * 50)
        logger.info("📊 CONNECTION TEST SUMMARY")
        logger.info("=" * 50)
        logger.info(f"⏱️  Connection duration: {connection_age:.1f} seconds")
        logger.info(f"📨 Total messages received: {self.message_count}")
        logger.info(f"📋 Subscription responses: {len(self.subscription_responses)}")
        
        if self.subscription_responses:
            logger.info("📋 Subscription details:")
            for resp in self.subscription_responses:
                logger.info(f"   - {resp}")
        
        # Анализ проблемы
        if connection_age < 35:
            logger.warning("⚠️  CONNECTION CLOSED TOO EARLY!")
            logger.warning("🔍 Possible causes:")
            logger.warning("   1. Invalid subscription parameters")
            logger.warning("   2. Server-side connection limits")
            logger.warning("   3. Authentication issues")
            logger.warning("   4. Rate limiting")
        elif 30 <= connection_age <= 35:
            logger.warning("⚠️  CONNECTION CLOSED AT ~30 SECONDS")
            logger.warning("🔍 This matches MEXC documentation:")
            logger.warning("   'If there is no valid websocket subscription, server disconnects in 30 seconds'")
            if len(self.subscription_responses) == 0:
                logger.error("❌ NO SUBSCRIPTION RESPONSES RECEIVED!")
                logger.error("   This indicates subscription requests were not processed")
            elif not any(r.get('code') == 0 for r in self.subscription_responses):
                logger.error("❌ ALL SUBSCRIPTIONS FAILED!")
                logger.error("   Check subscription parameters and symbol validity")
        else:
            logger.info("✅ Connection lasted longer than 30 seconds - good!")
            
        logger.info("=" * 50)


async def main():
    """Основная функция."""
    debug_client = MEXCDebugClient()
    await debug_client.test_market_connection()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("🛑 Test interrupted by user")
    except Exception as e:
        logger.error(f"💥 Test failed: {e}")