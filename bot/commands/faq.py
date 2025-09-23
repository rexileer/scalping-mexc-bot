from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto, InputMediaVideo
from aiogram.filters import Command
from faq.models import FAQ
from aiogram.types import FSInputFile
from bot.keyboards.inline import get_faq_keyboard
from bot.logger import logger
from bot.utils.bot_logging import log_command, log_callback

router = Router()


# Функция генерации клавиатуры из списка FAQ


# Команда /faq
@router.message(Command("faq"))
async def send_faq(message: Message):
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name or str(user_id)
    command = "/faq"
    response_text = "Выберите вопрос:"
    success = True
    extra_data = {"username": username, "chat_id": message.chat.id}
    
    try:
        keyboard = get_faq_keyboard()
        await message.answer(response_text, reply_markup=keyboard)
        
        # Получаем количество FAQ для логирования
        faq_count = await FAQ.objects.acount()
        extra_data["faq_count"] = faq_count
        
    except Exception as e:
        logger.exception(f"Ошибка при отображении FAQ для {user_id}")
        response_text = f"Ошибка при загрузке FAQ: {str(e)}"
        success = False
        await message.answer(response_text)
    
    # Логируем команду и ответ
    await log_command(
        user_id=user_id,
        command=command,
        response=response_text,
        success=success,
        extra_data=extra_data
    )


# Обработка нажатия на инлайн кнопку
@router.callback_query(F.data.startswith('faq_'))
async def process_faq_callback(callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    username = callback_query.from_user.username or callback_query.from_user.first_name or str(user_id)
    callback_data = callback_query.data
    response_text = ""
    success = True
    extra_data = {
        "username": username, 
        "chat_id": callback_query.message.chat.id,
        "callback_data": callback_data
    }
    
    try:
        faq_id = callback_query.data.split('_')[1]
        extra_data["faq_id"] = faq_id
        
        faq = await FAQ.objects.aget(id=faq_id)
        extra_data["question"] = faq.question
        extra_data["has_file"] = bool(faq.file)
        extra_data["media_type"] = faq.media_type if faq.file else None

        # Ответ на вопрос
        response_text = f"<b>{faq.question}</b>\n\n{faq.answer}"
        keyboard = get_faq_keyboard()

        try:
            if faq.file:
                file = FSInputFile(faq.file.path)
                if faq.media_type == 'image':
                    media = InputMediaPhoto(media=file, caption=response_text, parse_mode="HTML")
                elif faq.media_type == 'video':
                    media = InputMediaVideo(media=file, caption=response_text, parse_mode="HTML")
                else:
                    raise ValueError("Unsupported media type")

                await callback_query.message.edit_media(media=media, reply_markup=keyboard)

            else:
                await callback_query.message.edit_text(
                    text=response_text,
                    parse_mode="HTML",
                    reply_markup=keyboard
                )

        except Exception as e:
            extra_data["edit_error"] = str(e)
            logger.warning(f"Не удалось отредактировать сообщение FAQ: {e}")
            
            # В случае ошибки (например, нельзя редактировать сообщение), удалим и отправим заново
            await callback_query.message.delete()

            if faq.file:
                if faq.media_type == 'image':
                    await callback_query.message.answer_photo(FSInputFile(faq.file.path), caption=response_text, parse_mode="HTML", reply_markup=keyboard)
                elif faq.media_type == 'video':
                    await callback_query.message.answer_video(FSInputFile(faq.file.path), caption=response_text, parse_mode="HTML", reply_markup=keyboard)
            else:
                await callback_query.message.answer(response_text, parse_mode="HTML", reply_markup=keyboard)

        await callback_query.answer()
    except Exception as e:
        logger.exception(f"Ошибка при обработке callback FAQ для {user_id}")
        response_text = "Ошибка при загрузке FAQ"
        success = False
        await callback_query.answer("Произошла ошибка при загрузке FAQ", show_alert=True)
        extra_data["error"] = str(e)
    
    # Логируем callback и ответ
    await log_callback(
        user_id=user_id,
        callback_data=callback_data,
        response=response_text,
        success=success,
        extra_data=extra_data
    )
