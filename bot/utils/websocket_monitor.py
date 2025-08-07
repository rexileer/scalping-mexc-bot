#!/usr/bin/env python3
"""
WebSocket Connection Monitor Utility

Утилита для мониторинга и управления WebSocket соединениями.
Может быть запущена как standalone script или интегрирована в Django management commands.
"""

import asyncio
import time
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)


class WebSocketMonitor:
    """Monitor for WebSocket connections health and performance."""
    
    def __init__(self, websocket_manager):
        self.ws_manager = websocket_manager
        self.start_time = time.time()
        self.stats_history = []
        self.max_history = 100  # Храним последние 100 записей статистики
        
    async def run_monitor(self, interval: int = 30):
        """
        Запуск мониторинга соединений.
        
        Args:
            interval: Интервал между проверками в секундах
        """
        logger.info(f"Starting WebSocket monitor with {interval}s interval")
        
        while not self.ws_manager.is_shutting_down:
            try:
                await self.check_and_log_stats()
                await self.check_connection_health()
                await asyncio.sleep(interval)
            except Exception as e:
                logger.error(f"Error in WebSocket monitor: {e}")
                await asyncio.sleep(interval)
    
    async def check_and_log_stats(self):
        """Проверка и логирование статистики соединений."""
        stats = await self.ws_manager.get_connection_stats()
        health = await self.ws_manager.health_check()
        
        # Добавляем timestamp к статистике
        stats_with_time = {
            'timestamp': time.time(),
            **stats,
            **health
        }
        
        # Сохраняем в историю
        self.stats_history.append(stats_with_time)
        if len(self.stats_history) > self.max_history:
            self.stats_history.pop(0)
        
        # Логируем критические проблемы
        if stats['closed_sessions'] > 0:
            logger.warning(f"Found {stats['closed_sessions']} closed sessions that need cleanup")
            
        if health['unhealthy_user_connections'] > 0:
            logger.warning(f"Found {health['unhealthy_user_connections']} unhealthy user connections")
            
        if not health['market_connection_healthy'] and self.ws_manager.market_subscriptions:
            logger.warning("Market connection is unhealthy but subscriptions exist")
        
        # Логируем общую статистику каждые 5 минут
        uptime = time.time() - self.start_time
        if int(uptime) % 300 == 0:  # Каждые 5 минут
            logger.info(
                f"WebSocket Monitor Stats: "
                f"Users: {stats['user_connections']}, "
                f"Market: {'OK' if health['market_connection_healthy'] else 'FAIL'}, "
                f"Active Sessions: {stats['active_sessions']}, "
                f"Uptime: {uptime/3600:.1f}h"
            )
    
    async def check_connection_health(self):
        """Проверка здоровья соединений и автоматическое восстановление."""
        health = await self.ws_manager.health_check()
        
        # Если есть проблемы, пытаемся их исправить
        if health['issues']:
            logger.info(f"Detected {len(health['issues'])} connection issues, attempting fixes...")
            
            # Очистка закрытых сессий
            cleanup_count = await self.ws_manager.force_cleanup_sessions()
            if cleanup_count > 0:
                logger.info(f"Cleaned up {cleanup_count} stale sessions")
    
    def get_stats_summary(self) -> Dict[str, Any]:
        """Получение сводки статистики за период мониторинга."""
        if not self.stats_history:
            return {}
        
        latest = self.stats_history[-1]
        oldest = self.stats_history[0]
        
        return {
            'monitoring_duration': latest['timestamp'] - oldest['timestamp'],
            'current_stats': latest,
            'total_history_records': len(self.stats_history),
            'avg_user_connections': sum(s['user_connections'] for s in self.stats_history) / len(self.stats_history),
            'avg_active_sessions': sum(s['active_sessions'] for s in self.stats_history) / len(self.stats_history),
            'market_uptime_percent': (
                sum(1 for s in self.stats_history if s['market_connection_healthy']) 
                / len(self.stats_history) * 100
            )
        }
    
    async def force_reconnect_all(self):
        """Принудительное переподключение всех соединений."""
        logger.info("Starting force reconnect of all connections")
        
        # Отключаем все соединения
        await self.ws_manager.disconnect_all()
        await asyncio.sleep(2)
        
        # Переподключаем market data
        if self.ws_manager.market_subscriptions:
            logger.info("Reconnecting market data...")
            await self.ws_manager.connect_market_data()
        
        # Переподключаем пользователей
        logger.info("Reconnecting user connections...")
        await self.ws_manager.connect_valid_users()
        
        logger.info("Force reconnect completed")
    
    async def emergency_cleanup(self):
        """Экстренная очистка всех ресурсов."""
        logger.warning("Starting emergency cleanup")
        
        try:
            # Принудительная очистка сессий
            await self.ws_manager.force_cleanup_sessions()
            
            # Отключение всех соединений
            await self.ws_manager.disconnect_all()
            
            # Очистка внутренних структур данных
            self.ws_manager.price_callbacks.clear()
            self.ws_manager.bookticker_callbacks.clear()
            self.ws_manager.current_bookticker.clear()
            self.ws_manager.reconnecting_users.clear()
            
            logger.warning("Emergency cleanup completed")
            
        except Exception as e:
            logger.error(f"Error during emergency cleanup: {e}")


async def run_standalone_monitor():
    """Запуск standalone мониторинга (для тестирования)."""
    # Этот код можно использовать для запуска мониторинга отдельно
    import os
    import sys
    import django
    
    # Настройка Django
    sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'scalping_bot.settings')
    django.setup()
    
    from bot.utils.websocket_manager import websocket_manager
    
    monitor = WebSocketMonitor(websocket_manager)
    
    try:
        # Запуск мониторинга и самого WebSocket менеджера
        await asyncio.gather(
            websocket_manager.monitor_connections(),
            monitor.run_monitor(interval=30)
        )
    except KeyboardInterrupt:
        logger.info("Monitor stopped by user")
    finally:
        await websocket_manager.disconnect_all()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    asyncio.run(run_standalone_monitor())