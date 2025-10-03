"""
Базовые тесты без внешних зависимостей
"""
import os
import django

# Импортируем mock для mexc-sdk
import mock_mexc

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from django.test import TestCase
from django.conf import settings


class BasicTest(TestCase):
    """Базовые тесты системы"""
    
    def test_django_settings(self):
        """Тест что Django настройки загружаются"""
        self.assertTrue(hasattr(settings, 'SECRET_KEY'))
        self.assertTrue(hasattr(settings, 'DATABASES'))
        
    def test_database_config(self):
        """Тест конфигурации базы данных"""
        db_config = settings.DATABASES['default']
        self.assertEqual(db_config['ENGINE'], 'django.db.backends.postgresql')
        
    def test_installed_apps(self):
        """Тест что все приложения установлены"""
        apps = settings.INSTALLED_APPS
        self.assertIn('users', apps)
        self.assertIn('subscriptions', apps)
        self.assertIn('parameters', apps)
        self.assertIn('logs', apps)
