from bot.config import bot_instance
from aiogram import Bot
from django.conf import settings
from bot.logger import logger

async def get_bot_instance():
    """
    Возвращает экземпляр бота. Если бот еще не инициализирован, возвращает None.
    
    Returns:
        Bot: Экземпляр бота или None, если бот не инициализирован
    """
    if bot_instance is None:
        logger.warning("Bot instance not initialized yet. Main bot is not started or not accessible.")
    return bot_instance

async def send_message_safely(user_id, text, parse_mode=None, **kwargs):
    """
    Отправляет сообщение пользователю, используя глобальный экземпляр бота.
    Если глобальный экземпляр недоступен, создает временный экземпляр для отправки.
    
    Args:
        user_id (int): ID пользователя Telegram
        text (str): Текст сообщения
        parse_mode (str, optional): Режим парсинга текста. По умолчанию None.
        **kwargs: Дополнительные параметры для метода send_message
        
    Returns:
        Message: Объект отправленного сообщения или None в случае ошибки
    """
    temp_bot = None
    try:
        # Пытаемся использовать глобальный экземпляр бота
        bot = bot_instance
        
        # Если глобальный экземпляр недоступен, создаем временный
        if bot is None:
            logger.info("Using temporary bot instance for message sending")
            temp_bot = Bot(token=settings.TELEGRAM_BOT_TOKEN)
            bot = temp_bot
        
        return await bot.send_message(user_id, text, parse_mode=parse_mode, **kwargs)
    except Exception as e:
        logger.error(f"Error sending message to user {user_id}: {e}")
        return None
    finally:
        # Закрываем сессию временного бота, если он был создан
        if temp_bot is not None:
            try:
                await temp_bot.session.close()
            except Exception as e:
                logger.error(f"Error closing temporary bot session: {e}") 