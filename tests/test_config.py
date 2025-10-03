"""
Базовые тесты для конфигурации
"""
import os
import django

# Импортируем mock для mexc-sdk
import mock_mexc

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from django.test import TestCase
from bot.config import load_config


class ConfigTest(TestCase):
    """Тесты для конфигурации"""
    
    def test_load_config(self):
        """Тест загрузки конфигурации"""
        config = load_config()
        self.assertIsNotNone(config)
        self.assertIsNotNone(config.bot_token)
        self.assertIsNotNone(config.pair)
    
    def test_config_has_required_fields(self):
        """Тест наличия обязательных полей"""
        config = load_config()
        self.assertTrue(hasattr(config, 'bot_token'))
        self.assertTrue(hasattr(config, 'pair'))

