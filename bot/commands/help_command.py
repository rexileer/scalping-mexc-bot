from aiogram import Router, F
from aiogram.types import Message
from aiogram.filters import Command
from bot.logger import logger
from bot.utils.bot_logging import log_command

router = Router()

@router.message(Command("help"))
async def handle_help_command(message: Message):
    """
    Обработчик команды /help - показывает список доступных команд
    """
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name or str(user_id)
    command = "/help"
    
    # Формируем список доступных команд
    available_commands = [
        "/start - Начать работу с ботом",
        "/help - Показать список доступных команд",
        "/set_keys - Установить API ключи для MEXC",
        "/faq - Часто задаваемые вопросы",
        "/subscription - Информация о подписке",
        "/parameters - Настройки параметров торговли",
        "/price - Показать текущую цену",
        "/buy - Купить криптовалюту",
        "/auto_buy - Настройка автоматической покупки",
        "/balance - Показать баланс",
        "/status - Статус текущих сделок",
        "/stats - Статистика торговли",
        "/example - Пример команды (для тестирования)"
    ]
    
    # Формируем ответное сообщение
    response_text = "📋 <b>Доступные команды:</b>\n\n" + "\n".join(available_commands)
    
    # Отправляем ответ пользователю
    await message.answer(response_text, parse_mode="HTML")
    
    # Логируем выполнение команды
    await log_command(
        user_id=user_id,
        command=command,
        response=response_text,
        extra_data={
            "username": username,
            "chat_id": message.chat.id
        }
    ) 