import hmac
import hashlib
import time
import requests
from mexc_sdk import Spot
from users.models import User
from logger import logger
from mexc_sdk import Trade
from utils.api_errors import parse_mexc_error

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

def check_mexc_keys(api_key: str, api_secret: str) -> bool:
    url = "https://api.mexc.com/api/v3/account"
    timestamp = int(time.time() * 1000)

    query_string = f"timestamp={timestamp}"
    signature = hmac.new(api_secret.encode(), query_string.encode(), hashlib.sha256).hexdigest()

    headers = {
        "X-MEXC-APIKEY": api_key
    }

    response = requests.get(f"{url}?{query_string}&signature={signature}", headers=headers)
    
    logger.info(f"Response status code: {response.status_code}, response text: {response.text}")
    # Проверяем, что статус код 200 (успех)
    error = ""
    if response.status_code != 200:
        error = parse_mexc_error(response.text)

    return response.status_code == 200, error


# Функция для получения клиента и валютной пары
def get_user_client(telegram_id: int):
    try:
        user = User.objects.get(telegram_id=telegram_id)
        
        # Проверяем наличие API ключей
        if not user.api_key or not user.api_secret:
            raise ValueError("API ключи не найдены")

        # Возвращаем клиент и валютную пару пользователя
        return Spot(
            api_key=user.api_key,
            api_secret=user.api_secret
        ), user.pair
    except User.DoesNotExist:
        raise ValueError("Пользователь не найден")
    except Exception as e:
        logger.error(f"Ошибка при получении клиента для пользователя {telegram_id}: {e}")
        raise ValueError(f"Ошибка: {e}")
    
    
def handle_mexc_response(response: dict, context: str = ""):
    if isinstance(response, dict) and response.get("code") and response.get("code") != 200:
        code = response.get("code")
        msg = response.get("msg", "No message")
        raise Exception(f"[MEXC ERROR] {context}: Code {code}, Message: {msg}")
    return response
