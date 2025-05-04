import hmac
import hashlib
import time
import requests
from mexc_sdk import Spot, Trade
from users.models import User
from bot.logger import logger
from bot.utils.api_errors import parse_mexc_error
from bot.utils.performance import measure_time
import asyncio
from typing import Tuple, Optional

def get_actual_order_status(user: User, symbol: str, order_id: str) -> str:
    trade_client = Trade(user.api_key, user.api_secret)
    try:
        response = trade_client.query_order(
            symbol=symbol,
            options={"orderId": order_id}
        )
        if not isinstance(response, dict):
            logger.error(f"⚠️ Ответ не является dict: {type(response)} — {response}")
            return "ERROR"

        return response.get("status", "UNKNOWN")

    except Exception as e:
        logger.exception(f"Ошибка при получении статуса ордера {order_id}: {e}")
        return "ERROR"

async def check_mexc_keys(api_key: str, api_secret: str) -> Tuple[bool, str]:
    """Проверка API ключей с улучшенной обработкой ошибок"""
    url = "https://api.mexc.com/api/v3/account"
    timestamp = int(time.time() * 1000)
    
    # Добавляем recvWindow для учета возможной рассинхронизации времени
    query_string = f"timestamp={timestamp}&recvWindow=5000"
    signature = hmac.new(api_secret.encode(), query_string.encode(), hashlib.sha256).hexdigest()
    
    headers = {
        "X-MEXC-APIKEY": api_key,
        "Content-Type": "application/json"
    }
    
    try:
        response = requests.get(
            f"{url}?{query_string}&signature={signature}", 
            headers=headers,
            timeout=10  # Добавляем таймаут
        )
        
        if response.status_code == 200:
            return True, ""
            
        error = parse_mexc_error(response.text)
        if "700007" in error:
            return False, (
                "Ошибка доступа к API. Пожалуйста, проверьте:\n"
                "1. IP адрес сервера добавлен в список доверенных IP\n"
                "2. API ключ имеет разрешения на торговлю\n"
                "3. API ключ активен и не заблокирован"
            )
            
        return False, error
        
    except requests.exceptions.RequestException as e:
        return False, f"Ошибка сети: {str(e)}"

def get_user_client(telegram_id):
    """
    Получает клиент MEXC и торговую пару для пользователя
    """
    try:
        user = User.objects.get(telegram_id=telegram_id)
        if not user.api_key or not user.api_secret:
            raise ValueError("API ключи не настроены")
        
        client = Spot(
            api_key=user.api_key,
            api_secret=user.api_secret
        )
        
        return client, user.pair
    except User.DoesNotExist:
        raise ValueError("Пользователь не найден")
    except Exception as e:
        logger.error(f"Ошибка при получении клиента MEXC: {e}")
        raise

def handle_mexc_response(response):
    """
    Обрабатывает ответ от MEXC API
    """
    if isinstance(response, dict) and 'code' in response:
        if response['code'] == 0:
            return response['data']
        else:
            raise Exception(f"MEXC API Error: {response['msg']}")
    return response

def get_actual_order_status(client, order_id, symbol):
    """
    Получает актуальный статус ордера
    """
    try:
        order = client.get_order(order_id=order_id, symbol=symbol)
        return handle_mexc_response(order)
    except Exception as e:
        logger.error(f"Ошибка при получении статуса ордера: {e}")
        raise
