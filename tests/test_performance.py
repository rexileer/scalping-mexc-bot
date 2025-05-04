import asyncio
import time
from datetime import datetime, timedelta
import pytest
from bot.utils.performance import measure_time, Cache, bulk_process, global_cache
from bot.utils.mexc import check_mexc_keys
from bot.middlewares.auth_middleware import AuthMiddleware
from bot.commands.states import APIAuth
from aiogram.types import Message, User as TelegramUser
from aiogram.fsm.context import FSMContext
from unittest.mock import Mock, patch, AsyncMock
from django.core.exceptions import ObjectDoesNotExist
from users.models import User

@pytest.fixture
async def cleanup_db():
    print("\n=== Starting cleanup_db fixture ===")
    # Очищаем кэш перед каждым тестом
    global_cache.clear()
    print("Cache cleared")
    
    # Очищаем базу данных
    count_before = await User.objects.acount()
    print(f"Users in database before cleanup: {count_before}")
    
    await User.objects.all().adelete()
    await asyncio.sleep(0.1)
    
    count_after = await User.objects.acount()
    print(f"Users in database after cleanup: {count_after}")
    print("=== Finished cleanup_db fixture ===\n")
    
    yield
    
    print("\n=== Starting cleanup_db teardown ===")
    global_cache.clear()
    await User.objects.all().adelete()
    await asyncio.sleep(0.1)
    print("=== Finished cleanup_db teardown ===\n")

@pytest.mark.asyncio
async def test_cache():
    cache = Cache(timeout_minutes=1)
    
    # Тест установки и получения значения
    cache.set("test_key", "test_value")
    assert cache.get("test_key") == "test_value"
    
    # Тест истечения срока действия
    cache.timeout = timedelta(seconds=0)
    assert cache.get("test_key") is None
    
    # Тест очистки кэша
    cache.set("test_key", "test_value")
    cache.clear()
    assert cache.get("test_key") is None

@pytest.mark.asyncio
async def test_measure_time():
    @measure_time
    async def test_function():
        await asyncio.sleep(0.1)
        return "test"
    
    result = await test_function()
    assert result == "test"

@pytest.mark.asyncio
async def test_bulk_process():
    async def process_item(item):
        await asyncio.sleep(0.1)
        return item * 2
    
    items = list(range(20))
    results = await bulk_process(items, process_item, chunk_size=5)
    assert len(results) == 20
    assert results == [i * 2 for i in items]

@pytest.mark.django_db
@pytest.mark.asyncio
async def test_auth_middleware(cleanup_db):
    print("\n=== Starting test_auth_middleware ===")
    # Подготовка тестового окружения
    middleware = AuthMiddleware()
    telegram_id = 123
    
    # Базовые моки
    mock_telegram_user = Mock(spec=TelegramUser)
    mock_telegram_user.id = telegram_id
    
    mock_message = Mock(spec=Message)
    mock_message.from_user = mock_telegram_user
    mock_message.text = "/test"
    mock_message.answer = AsyncMock()
    
    mock_state = AsyncMock(spec=FSMContext)
    mock_state.get_state.return_value = None
    
    # Тестовый handler
    async def test_handler(event, data):
        return "success"
    
    # Тест 1: Несуществующий пользователь
    print("\n--- Test 1: Non-existent user ---")
    result = await middleware(test_handler, mock_message, {"state": mock_state})
    assert result is None
    mock_message.answer.assert_called_once_with(
        "Вы не зарегистрированы. Используйте /set_keys для авторизации."
    )
    
    # Сброс моков
    mock_message.answer.reset_mock()
    
    # Тест 2: Разрешенная команда
    print("\n--- Test 2: Allowed command ---")
    mock_message.text = "/help"
    result = await middleware(test_handler, mock_message, {"state": mock_state})
    assert result == "success"
    mock_message.answer.assert_not_called()
    
    # Сброс моков
    mock_message.answer.reset_mock()
    mock_message.text = "/test"
    
    # Тест 3: Состояние ввода ключей
    print("\n--- Test 3: API key input state ---")
    mock_state.get_state.return_value = APIAuth.waiting_for_api_key.state
    result = await middleware(test_handler, mock_message, {"state": mock_state})
    assert result == "success"
    mock_message.answer.assert_not_called()
    
    # Сброс моков
    mock_message.answer.reset_mock()
    mock_state.get_state.return_value = None
    
    # Тест 4: Пользователь без ключей
    print("\n--- Test 4: User without keys ---")
    user = await User.objects.acreate(
        telegram_id=telegram_id,
        name="Test User",
        autobuy=False
    )
    
    # Проверяем, что пользователь создался
    user_count = await User.objects.acount()
    print(f"Users in database: {user_count}")
    user = await User.objects.aget(telegram_id=telegram_id)
    print(f"Found user: {user.telegram_id}, api_key: {user.api_key}, api_secret: {user.api_secret}")
    
    result = await middleware(test_handler, mock_message, {"state": mock_state})
    assert result is None
    mock_message.answer.assert_called_once_with(
        "Пожалуйста, сначала введите API ключи через /set_keys."
    )
    
    # Сброс моков
    mock_message.answer.reset_mock()
    
    # Тест 5: Пользователь с ключами
    print("\n--- Test 5: User with keys ---")
    user.api_key = "db_key"
    user.api_secret = "db_secret"
    await user.asave()
    
    # Проверяем, что ключи сохранились
    user = await User.objects.aget(telegram_id=telegram_id)
    print(f"User after update: {user.telegram_id}, api_key: {user.api_key}, api_secret: {user.api_secret}")
    
    result = await middleware(test_handler, mock_message, {"state": mock_state})
    assert result == "success"
    mock_message.answer.assert_not_called()
    
    # Проверка кэша
    cached_data = global_cache.get(f"user_{telegram_id}")
    assert cached_data is not None
    assert cached_data['api_key'] == "db_key"
    assert cached_data['api_secret'] == "db_secret"
    
    # Сброс моков и кэша
    mock_message.answer.reset_mock()
    global_cache.clear()
    
    # Тест 6: Данные в кэше
    print("\n--- Test 6: Cached data ---")
    global_cache.set(f"user_{telegram_id}", {
        'api_key': 'cached_key',
        'api_secret': 'cached_secret'
    })
    result = await middleware(test_handler, mock_message, {"state": mock_state})
    assert result == "success"
    mock_message.answer.assert_not_called()
    
    print("\n=== Finished test_auth_middleware ===")

@pytest.mark.asyncio
async def test_mexc_api():
    # Тест с неверными ключами
    is_valid, error = await check_mexc_keys("invalid_key", "invalid_secret")
    assert not is_valid
    assert "Неверная пара API-ключей" in error

if __name__ == "__main__":
    asyncio.run(pytest.main([__file__, "-v"])) 