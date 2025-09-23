import hmac
import hashlib
import time
import requests
import aiohttp
from mexc_sdk import Spot
from users.models import User
from bot.logger import logger
from utils.api_errors import parse_mexc_error
from bot.utils.mexc_rest import MexcRestClient

def get_actual_order_status(user: User, symbol: str, order_id: str) -> str:
    """Synchronous wrapper used via sync_to_async in async contexts."""
    client = MexcRestClient(user.api_key, user.api_secret)
    import asyncio as _asyncio
    try:
        loop = _asyncio.new_event_loop()
        _asyncio.set_event_loop(loop)
        try:
            response = loop.run_until_complete(client.query_order(symbol, {"orderId": order_id}))
        finally:
            loop.run_until_complete(_asyncio.sleep(0))
            loop.close()
        if not isinstance(response, dict):
            logger.error(f"⚠️ Ответ не является dict: {type(response)} — {response}")
            return "ERROR"
        return response.get("status", "UNKNOWN")
    except Exception as e:
        logger.exception(f"Ошибка при получении статуса ордера {order_id}: {e}")
        return "ERROR"

# Синхронная версия для обратной совместимости
def check_mexc_keys(api_key: str, api_secret: str) -> tuple:
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

# Новая асинхронная версия
async def check_mexc_keys_async(api_key: str, api_secret: str) -> tuple:
    url = "https://api.mexc.com/api/v3/account"
    timestamp = int(time.time() * 1000)

    query_string = f"timestamp={timestamp}"
    signature = hmac.new(api_secret.encode(), query_string.encode(), hashlib.sha256).hexdigest()

    headers = {
        "X-MEXC-APIKEY": api_key
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{url}?{query_string}&signature={signature}", headers=headers) as response:
                status_code = response.status
                response_text = await response.text()
                logger.info(f"Response status code: {status_code}, response text: {response_text}")
                
                # Проверяем наличие ошибок
                if status_code != 200:
                    # Обработка ошибки IP whitelist
                    if "700006" in response_text and "ip white list" in response_text.lower():
                        error_msg = "IP адрес вашего сервера не добавлен в белый список. Пожалуйста, откройте настройки API ключа на MEXC и добавьте IP ограничения, либо уберите ограничения по IP."
                        logger.warning(f"IP не в белом списке: {response_text}")
                        return False, error_msg
                    
                    # Другие ошибки
                    error = parse_mexc_error(response_text)
                    return False, error
                
                # Если статус 200, ключи валидны
                return True, ""
    except Exception as e:
        logger.error(f"Ошибка при проверке ключей API: {e}")
        return False, f"Ошибка соединения: {str(e)}"


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
