import logging
from typing import Optional, Dict, Any, Union
from bot.logger import logger, log_to_db

async def find_user_by_telegram_id(user_id: Union[int, str]) -> Optional["User"]:
    """
    Асинхронно находит пользователя по telegram_id
    
    :param user_id: ID пользователя в Telegram
    :return: Объект пользователя или None
    """
    try:
        from users.models import User
        from asgiref.sync import sync_to_async
        
        # Преобразуем ID в число, если это строка
        if isinstance(user_id, str) and user_id.isdigit():
            user_id = int(user_id)
        elif not isinstance(user_id, int):
            return None
            
        # Используем sync_to_async для работы с БД асинхронно
        user = await sync_to_async(User.objects.filter(telegram_id=user_id).first)()
        return user
    except Exception as e:
        logger.error(f"Ошибка при поиске пользователя: {e}")
        return None

async def log_user_action(
    user_id: Union[int, str],
    action: str,
    level: str = 'INFO',
    extra_data: Optional[Dict[str, Any]] = None
) -> None:
    """
    Логирует действие пользователя в стандартный лог и в базу данных.
    
    :param user_id: ID пользователя в Telegram
    :param action: Описание действия
    :param level: Уровень логирования ('INFO', 'WARNING', 'ERROR', 'DEBUG')
    :param extra_data: Дополнительные данные для логирования
    """
    try:
        # Логируем в стандартный лог
        log_message = f"User {user_id}: {action}"
        
        if level.upper() == 'ERROR':
            logger.error(log_message)
        elif level.upper() == 'WARNING':
            logger.warning(log_message)
        elif level.upper() == 'DEBUG':
            logger.debug(log_message)
        else:
            logger.info(log_message)
        
        # Найдем пользователя в базе данных
        user = await find_user_by_telegram_id(user_id)
            
        # Логируем в базу данных
        await log_to_db(
            message=action,
            level=level,
            user=user,
            extra_data={
                'user_id': user_id,
                **(extra_data or {})
            }
        )
    except Exception as e:
        logger.error(f"Error logging user action: {e}")

async def log_api_call(
    method: str,
    params: Dict[str, Any],
    result: Any,
    success: bool,
    user_id: Optional[Union[int, str]] = None,
    level: str = 'INFO'
) -> None:
    """
    Логирует вызовы API в стандартный лог и в базу данных.
    
    :param method: Название метода API
    :param params: Параметры запроса (без чувствительных данных)
    :param result: Результат вызова API
    :param success: Флаг успешности вызова
    :param user_id: ID пользователя (если применимо)
    :param level: Уровень логирования
    """
    try:
        # Формируем сообщение для лога - более компактное
        api_type = "MEXC API" if 'mexc' in method.lower() else "API"
        status = "✓" if success else "✗"
        log_message = f"{api_type} [{status}] {method}"
        if user_id:
            log_message = f"User {user_id}: {log_message}"
            
        # Логируем в стандартный лог
        log_level = level if success else 'ERROR'
        if log_level.upper() == 'ERROR':
            logger.error(log_message)
        elif log_level.upper() == 'WARNING':
            logger.warning(log_message)
        else:
            logger.info(log_message)
            
        # Пытаемся найти пользователя в базе данных
        user = None
        if user_id:
            user = await find_user_by_telegram_id(user_id)
                
        # Очищаем параметры от чувствительных данных и сокращаем объем
        safe_params = {}
        for key, value in params.items():
            if key.lower() not in ('api_key', 'api_secret', 'token', 'password'):
                # Сокращаем длинные значения
                if isinstance(value, str) and len(value) > 100:
                    safe_params[key] = value[:100] + '...'
                else:
                    safe_params[key] = value
            else:
                safe_params[key] = '***'
                
        # Логируем в базу данных с компактным представлением
        await log_to_db(
            message=log_message,
            level=log_level,
            user=user,
            extra_data={
                'method': method,
                'params': safe_params,
                'result': result,
                'success': success,
                'user_id': user_id,
            }
        )
    except Exception as e:
        logger.error(f"Error logging API call: {e}")

async def log_command(
    user_id: Union[int, str],
    command: str,
    response: Optional[str] = None,
    success: bool = True,
    extra_data: Optional[Dict[str, Any]] = None
) -> None:
    """
    Специальная функция для логирования команд бота.
    Создаёт единую запись о выполнении команды.
    
    :param user_id: ID пользователя в Telegram
    :param command: Имя команды (с /)
    :param response: Ответ бота пользователю
    :param success: Успешно ли выполнилась команда
    :param extra_data: Дополнительные данные для логирования
    """
    try:
        # Форматируем сообщение
        action = f"Выполнил команду: {command}"
        level = 'INFO' if success else 'ERROR'
        
        # Стандартное логирование в консоль
        log_message = f"User {user_id}: {action}"
        if level.upper() == 'ERROR':
            logger.error(log_message)
        else:
            logger.info(log_message)
        
        # Подготовка дополнительных данных
        command_data = extra_data or {}
        
        # Добавляем ответ, если он есть
        if response:
            # Если ответ слишком длинный, сокращаем его
            if isinstance(response, str) and len(response) > 500:
                command_data['response'] = response[:500] + '...'
            else:
                command_data['response'] = response
                
        # Добавляем статус выполнения
        command_data['success'] = success
        
        # Находим пользователя
        user = await find_user_by_telegram_id(user_id)
        
        # Логируем в БД единой записью
        await log_to_db(
            message=action,
            level=level,
            user=user,
            extra_data={
                'user_id': user_id,
                'command': command,
                **command_data
            }
        )
    except Exception as e:
        logger.error(f"Error logging bot command: {e}")

async def log_callback(
    user_id: Union[int, str],
    callback_data: str,
    response: Optional[str] = None,
    success: bool = True,
    extra_data: Optional[Dict[str, Any]] = None
) -> None:
    """
    Функция для логирования callback-запросов (нажатий на кнопки).
    
    :param user_id: ID пользователя в Telegram
    :param callback_data: Данные callback-запроса
    :param response: Ответ бота
    :param success: Успешно ли обработан callback
    :param extra_data: Дополнительные данные
    """
    try:
        # Форматируем сообщение
        callback_preview = callback_data
        if len(callback_data) > 50:
            callback_preview = callback_data[:47] + "..."
        
        action = f"Нажал кнопку: {callback_preview}"
        level = 'INFO' if success else 'ERROR'
        
        # Стандартное логирование в консоль
        log_message = f"User {user_id}: {action}"
        if level.upper() == 'ERROR':
            logger.error(log_message)
        else:
            logger.info(log_message)
        
        # Подготовка дополнительных данных
        callback_info = extra_data or {}
        callback_info['callback_data'] = callback_data
        
        # Добавляем ответ, если он есть
        if response:
            callback_info['response'] = response
                
        # Добавляем статус выполнения
        callback_info['success'] = success
        
        # Находим пользователя
        user = await find_user_by_telegram_id(user_id)
        
        # Логируем в БД единой записью
        await log_to_db(
            message=action,
            level=level,
            user=user,
            extra_data={
                'user_id': user_id,
                **callback_info
            }
        )
    except Exception as e:
        logger.error(f"Error logging callback: {e}") 