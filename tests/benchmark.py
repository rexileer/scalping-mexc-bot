import asyncio
import time
from datetime import datetime
import logging
from bot.utils.performance import measure_time, Cache, bulk_process
from bot.utils.mexc import check_mexc_keys, get_user_client
from bot.middlewares.auth_middleware import AuthMiddleware
from users.models import User

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def benchmark_cache():
    logger.info("Тестирование кэша...")
    cache = Cache(timeout_minutes=1)
    
    # Тест записи
    start_time = time.time()
    for i in range(1000):
        cache.set(f"key_{i}", f"value_{i}")
    write_time = time.time() - start_time
    logger.info(f"Время записи 1000 значений: {write_time:.3f} сек")
    
    # Тест чтения
    start_time = time.time()
    for i in range(1000):
        cache.get(f"key_{i}")
    read_time = time.time() - start_time
    logger.info(f"Время чтения 1000 значений: {read_time:.3f} сек")

async def benchmark_auth_middleware():
    logger.info("Тестирование middleware...")
    middleware = AuthMiddleware()
    
    # Создаем тестового пользователя
    user = await User.objects.acreate(
        telegram_id=123456,
        api_key="test_key",
        api_secret="test_secret"
    )
    
    # Тест обработки сообщения
    start_time = time.time()
    for _ in range(100):
        message = type('Message', (), {
            'from_user': type('User', (), {'id': 123456}),
            'text': '/test'
        })
        await middleware(lambda: "success", message, {})
    middleware_time = time.time() - start_time
    logger.info(f"Время обработки 100 сообщений: {middleware_time:.3f} сек")
    
    # Очистка
    await user.adelete()

async def benchmark_mexc_api():
    logger.info("Тестирование MEXC API...")
    
    # Тест проверки ключей
    start_time = time.time()
    for _ in range(10):
        await check_mexc_keys("invalid_key", "invalid_secret")
    api_time = time.time() - start_time
    logger.info(f"Время 10 запросов к API: {api_time:.3f} сек")

async def benchmark_bulk_processing():
    logger.info("Тестирование массовой обработки...")
    
    async def process_item(item):
        await asyncio.sleep(0.01)
        return item * 2
    
    items = list(range(100))
    
    # Тест без bulk processing
    start_time = time.time()
    results = []
    for item in items:
        result = await process_item(item)
        results.append(result)
    normal_time = time.time() - start_time
    logger.info(f"Время обработки 100 элементов без bulk: {normal_time:.3f} сек")
    
    # Тест с bulk processing
    start_time = time.time()
    results = await bulk_process(items, process_item, chunk_size=10)
    bulk_time = time.time() - start_time
    logger.info(f"Время обработки 100 элементов с bulk: {bulk_time:.3f} сек")
    
    speedup = normal_time / bulk_time
    logger.info(f"Ускорение: {speedup:.2f}x")

async def main():
    logger.info("Начало бенчмаркинга...")
    
    await benchmark_cache()
    await benchmark_auth_middleware()
    await benchmark_mexc_api()
    await benchmark_bulk_processing()
    
    logger.info("Бенчмаркинг завершен")

if __name__ == "__main__":
    asyncio.run(main()) 