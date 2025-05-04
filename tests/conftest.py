import os
import django
import pytest

# Устанавливаем переменные окружения для тестов
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
os.environ.setdefault('TESTING', '1')

# Инициализируем Django
django.setup()

@pytest.fixture(autouse=True)
def setup_django():
    """Фикстура для настройки Django перед каждым тестом"""
    yield 