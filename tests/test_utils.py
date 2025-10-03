"""
Базовые тесты для утилит
"""
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from django.test import TestCase
from bot.utils.api_errors import parse_mexc_error


class ApiErrorsTest(TestCase):
    """Тесты для обработки ошибок API"""
    
    def test_parse_mexc_error_with_code(self):
        """Тест парсинга ошибки с кодом"""
        error_response = {
            'code': -1003,
            'msg': 'Too many requests'
        }
        result = parse_mexc_error(error_response)
        self.assertIn('Too many requests', result)
        
    def test_parse_mexc_error_without_code(self):
        """Тест парсинга ошибки без кода"""
        error_response = {
            'msg': 'Unknown error'
        }
        result = parse_mexc_error(error_response)
        self.assertIn('Unknown error', result)
    
    def test_parse_mexc_error_string(self):
        """Тест парсинга строковой ошибки"""
        error = "Connection timeout"
        result = parse_mexc_error(error)
        # parse_mexc_error оборачивает неизвестные ошибки в HTML
        self.assertIn("Connection timeout", result)

