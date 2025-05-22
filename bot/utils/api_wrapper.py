import logging
import json
import traceback
from typing import Dict, Any, Optional, Callable, Awaitable, Union
from functools import wraps
from bot.utils.bot_logging import log_api_call

logger = logging.getLogger("TelegramBot")

def log_api_request(func):
    """
    Декоратор для логирования API запросов с MEXC
    
    Оборачивает асинхронные функции, которые делают запросы к API,
    логируя только важную информацию и результат
    """
    @wraps(func)
    async def wrapper(*args, **kwargs):
        # Получаем информацию о методе и параметрах
        method_name = func.__name__
        
        # Извлекаем параметры для логирования
        user_id = None
        params = {}
        
        # Собираем параметры из аргументов и kwargs
        for arg in args:
            # Если один из аргументов - словарь, считаем его параметрами запроса
            if isinstance(arg, dict):
                params.update(arg)
                
        # Собираем параметры из kwargs
        params.update(kwargs)
        
        # Пытаемся найти user_id в параметрах
        if 'user_id' in params:
            user_id = params['user_id']
        elif 'telegram_id' in params:
            user_id = params['telegram_id']
        
        try:
            # Выполняем API-запрос
            result = await func(*args, **kwargs)
            
            # Логируем только значимые вызовы API, связанные с MEXC
            if 'mexc' in method_name.lower() or 'trade' in method_name.lower() or 'order' in method_name.lower():
                # Определяем сокращенный результат для лога
                result_summary = result
                if isinstance(result, dict) and len(str(result)) > 1000:
                    # Если результат слишком большой, сокращаем его
                    result_summary = {'status': result.get('status', 'success'), 'summary': 'Большой результат'}
                    if 'data' in result:
                        result_summary['data_preview'] = str(result['data'])[:200] + '...'
                
                # Логируем успешный запрос к MEXC
                await log_api_call(
                    method=method_name,
                    params=params,
                    result=result_summary,
                    success=True,
                    user_id=user_id
                )
            
            return result
            
        except Exception as e:
            # Получаем информацию об ошибке
            error_info = {
                'error': str(e),
                'traceback': traceback.format_exc().split('\n')[-5:] # Сокращаем стектрейс
            }
            
            # Всегда логируем ошибки вызовов API
            await log_api_call(
                method=method_name,
                params=params,
                result=error_info,
                success=False,
                user_id=user_id,
                level='ERROR'
            )
            
            # Прокидываем исключение дальше
            raise
            
    return wrapper


# Пример использования:
# 
# @log_api_request
# async def get_mexc_balance(api_key: str, api_secret: str, user_id: int = None):
#     # Реализация запроса к MEXC API
#     result = await some_api_client.get_balance(api_key, api_secret)
#     return result 