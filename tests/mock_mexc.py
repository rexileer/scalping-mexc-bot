"""
Mock для mexc-sdk для тестов
"""
import sys
from unittest.mock import MagicMock

# Создаем mock модуль mexc_sdk
mexc_sdk_mock = MagicMock()
mexc_sdk_mock.Spot = MagicMock()

# Добавляем в sys.modules чтобы избежать ImportError
sys.modules['mexc_sdk'] = mexc_sdk_mock
sys.modules['mexc_sdk.Spot'] = mexc_sdk_mock.Spot
