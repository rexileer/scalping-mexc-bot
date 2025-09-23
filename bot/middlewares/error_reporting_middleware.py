from typing import Dict, Any, Callable, Awaitable

from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery

from bot.utils.error_notifier import (
    notify_user_command_error,
    notify_component_error,
)
from bot.utils.api_errors import parse_mexc_error


class ErrorReportingMiddleware(BaseMiddleware):
    """
    Catches unhandled exceptions in handlers and reports them to the
    NOTIFICATION_CHAT_ID in a human-friendly Russian format.
    """

    async def __call__(
        self,
        handler: Callable[[Message, Dict[str, Any]], Awaitable[Any]],
        event: Message | CallbackQuery,
        data: Dict[str, Any]
    ) -> Any:
        try:
            return await handler(event, data)
        except Exception as e:
            # Message handlers
            if isinstance(event, Message):
                user_id = event.from_user.id if event.from_user else "unknown"
                text = event.text or ""
                command = text.split()[0] if text.startswith("/") else "сообщение"
                human_message = parse_mexc_error(e)

                # Notify admins
                await notify_user_command_error(user_id, command, human_message)

                # Optional: inform user
                try:
                    await event.answer("Произошла ошибка. Попробуйте ещё раз позже.")
                except Exception:
                    pass

                return None

            # Callback handlers
            if isinstance(event, CallbackQuery):
                user_id = event.from_user.id if event.from_user else "unknown"
                data_str = (event.data or "")[:100]
                human_message = parse_mexc_error(e)
                await notify_component_error(
                    component="командных обработчиках",
                    human_message=f"Ошибка при обработке нажатия кнопки: {data_str}\n{human_message}",
                )
                try:
                    await event.answer("Произошла ошибка", show_alert=False)
                except Exception:
                    pass
                return None

            # Fallback: attempt generic notification
            try:
                await notify_component_error(
                    component="боте",
                    human_message=str(e),
                )
            except Exception:
                pass
            return None


