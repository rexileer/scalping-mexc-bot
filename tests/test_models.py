"""
Базовые тесты для моделей Django
"""
import os
import django

# Импортируем mock для mexc-sdk
import mock_mexc

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from django.test import TestCase
from users.models import User, Deal
from subscriptions.models import Subscription
from parameters.models import BaseParameters
from django.utils import timezone
from decimal import Decimal


class UserModelTest(TestCase):
    """Тесты для модели User"""
    
    def test_user_creation(self):
        """Тест создания пользователя"""
        user = User.objects.create(
            telegram_id=123456789,
            name="Test User",
            pair="BTCUSDT",
            profit=1.5,
            pause=60,
            loss=2.0,
            buy_amount=Decimal('10.00')
        )
        self.assertEqual(user.telegram_id, 123456789)
        self.assertEqual(user.name, "Test User")
        self.assertEqual(user.pair, "BTCUSDT")
        
    def test_user_str_representation(self):
        """Тест строкового представления"""
        user = User.objects.create(
            telegram_id=123456789,
            name="Test User"
        )
        self.assertEqual(str(user), "Test User")


class DealModelTest(TestCase):
    """Тесты для модели Deal"""
    
    def setUp(self):
        self.user = User.objects.create(
            telegram_id=123456789,
            name="Test User"
        )
    
    def test_deal_creation(self):
        """Тест создания сделки"""
        deal = Deal.objects.create(
            user=self.user,
            order_id="TEST123456",
            symbol="BTCUSDT",
            buy_price=Decimal('50000.00'),
            quantity=Decimal('0.001'),
            status="NEW"
        )
        self.assertEqual(deal.order_id, "TEST123456")
        self.assertEqual(deal.status, "NEW")
        self.assertEqual(deal.user, self.user)


class BaseParametersTest(TestCase):
    """Тесты для модели BaseParameters"""
    
    def test_base_parameters_singleton(self):
        """Тест что создается только одна запись"""
        params1 = BaseParameters.objects.create(
            profit=1.5,
            pause=60,
            loss=2.0,
            buy_amount=Decimal('10.00')
        )
        params2 = BaseParameters.objects.create(
            profit=2.0,
            pause=120,
            loss=3.0,
            buy_amount=Decimal('20.00')
        )
        # Должна быть только одна запись
        self.assertEqual(BaseParameters.objects.count(), 1)
        # Должна быть обновлена первая запись
        params = BaseParameters.objects.first()
        self.assertEqual(params.profit, 2.0)

