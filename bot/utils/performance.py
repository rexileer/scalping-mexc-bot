import time
import asyncio
from functools import wraps, lru_cache
from datetime import datetime, timedelta
from typing import Any, Callable, Dict
from bot.logger import logger

def measure_time(func):
    @wraps(func)
    async def wrapper(*args, **kwargs):
        start_time = time.time()
        result = await func(*args, **kwargs)
        end_time = time.time()
        logger.info(f"Function {func.__name__} took {end_time - start_time:.2f} seconds")
        return result
    return wrapper

class Cache:
    def __init__(self, timeout_minutes: int = 5):
        self.cache: Dict[str, Dict[str, Any]] = {}
        self.timeout = timedelta(minutes=timeout_minutes)
    
    def get(self, key: str) -> Any:
        if key in self.cache:
            cache_data = self.cache[key]
            if datetime.now() - cache_data['time'] < self.timeout:
                return cache_data['data']
        return None
    
    def set(self, key: str, data: Any):
        self.cache[key] = {
            'time': datetime.now(),
            'data': data
        }
    
    def clear(self):
        self.cache.clear()

# Глобальный кэш для использования в разных частях приложения
global_cache = Cache()

@lru_cache(maxsize=100)
async def get_user_data(telegram_id: int) -> dict:
    from users.models import User
    user = await User.objects.aget(telegram_id=telegram_id)
    return {
        'api_key': user.api_key,
        'api_secret': user.api_secret,
        'pair': user.pair
    }

async def bulk_process(items, processor, chunk_size=10):
    """Обработка элементов пакетами для оптимизации производительности"""
    results = []
    for i in range(0, len(items), chunk_size):
        chunk = items[i:i + chunk_size]
        tasks = [processor(item) for item in chunk]
        chunk_results = await asyncio.gather(*tasks)
        results.extend(chunk_results)
    return results 