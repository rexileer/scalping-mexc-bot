from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.filters import Command
from faq.models import FAQ  # Импортируем модель FAQ
from aiogram.types import FSInputFile

router = Router()

# Команда /faq
@router.message(Command("faq"))
async def send_faq(message: Message):
    # Получаем все вопросы
    faqs = FAQ.objects.all()

    # Формируем инлайн кнопки для каждого вопроса
    inline_buttons = []
    for faq in faqs:
        # Создаём кнопку для каждого вопроса
        button = InlineKeyboardButton(text=faq.question[:20], callback_data=f'faq_{faq.id}')
        inline_buttons.append([button])  # Каждая кнопка в своём списке

    # Создаём InlineKeyboardMarkup с указанием списка кнопок
    keyboard = InlineKeyboardMarkup(inline_keyboard=inline_buttons)

    await message.answer("Выберите вопрос:", reply_markup=keyboard)

# Обработка нажатия на инлайн кнопку
@router.callback_query(F.data.startswith('faq_'))
async def process_faq_callback(callback_query: CallbackQuery):
    faq_id = callback_query.data.split('_')[1]  # Получаем ID FAQ
    faq = FAQ.objects.get(id=faq_id)

    # Формируем ответ на вопрос
    response = f"**{faq.question}**\n\n{faq.answer}"

    # Если есть медиафайл, отправим его
    if faq.file:
        if faq.media_type == 'image':
            await callback_query.message.answer_photo(FSInputFile(faq.file.path), caption=response)
        elif faq.media_type == 'video':
            await callback_query.message.answer_video(FSInputFile(faq.file.path), caption=response)
    else:
        await callback_query.message.answer(response)

    # Подтверждаем обработку callback'а
    await callback_query.answer()
