from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto, InputMediaVideo
from aiogram.filters import Command
from faq.models import FAQ
from aiogram.types import FSInputFile
from bot.keyboards.inline import get_faq_keyboard

router = Router()


# Функция генерации клавиатуры из списка FAQ


# Команда /faq
@router.message(Command("faq"))
async def send_faq(message: Message):
    keyboard = get_faq_keyboard()
    await message.answer("Выберите вопрос:", reply_markup=keyboard)


# Обработка нажатия на инлайн кнопку
@router.callback_query(F.data.startswith('faq_'))
async def process_faq_callback(callback_query: CallbackQuery):
    faq_id = callback_query.data.split('_')[1]
    faq = FAQ.objects.get(id=faq_id)

    # Ответ на вопрос
    response = f"<b>{faq.question}</b>\n\n{faq.answer}"
    keyboard = get_faq_keyboard()

    try:
        if faq.file:
            file = FSInputFile(faq.file.path)
            if faq.media_type == 'image':
                media = InputMediaPhoto(media=file, caption=response, parse_mode="HTML")
            elif faq.media_type == 'video':
                media = InputMediaVideo(media=file, caption=response, parse_mode="HTML")
            else:
                raise ValueError("Unsupported media type")

            await callback_query.message.edit_media(media=media, reply_markup=keyboard)

        else:
            await callback_query.message.edit_text(
                text=response,
                parse_mode="HTML",
                reply_markup=keyboard
            )

    except Exception as e:
        # В случае ошибки (например, нельзя редактировать сообщение), удалим и отправим заново
        await callback_query.message.delete()

        if faq.file:
            if faq.media_type == 'image':
                await callback_query.message.answer_photo(FSInputFile(faq.file.path), caption=response, parse_mode="HTML", reply_markup=keyboard)
            elif faq.media_type == 'video':
                await callback_query.message.answer_video(FSInputFile(faq.file.path), caption=response, parse_mode="HTML", reply_markup=keyboard)
        else:
            await callback_query.message.answer(response, parse_mode="HTML", reply_markup=keyboard)

    await callback_query.answer()
