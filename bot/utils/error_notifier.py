import asyncio
import logging
import re
from typing import Optional, List, Union
import time
import hashlib

import os
from django.conf import settings

from aiogram import Bot
from asgiref.sync import sync_to_async
from bot.utils.api_errors import parse_mexc_error, ERROR_MESSAGES


def _parse_chat_id(raw: str) -> Union[int, str]:
    raw = (raw or '').strip()
    if not raw:
        return ''
    try:
        return int(raw)
    except (TypeError, ValueError):
        return raw


def _get_notification_chat_ids() -> List[Union[int, str]]:
    # Preferred plural env/setting
    candidates = (
        getattr(settings, 'NOTIFICATION_CHAT_IDS', None)
        or os.getenv('NOTIFICATION_CHAT_IDS')
    )

    # Fallbacks: single chat and channel ids
    if not candidates:
        single = getattr(settings, 'NOTIFICATION_CHAT_ID', None) or os.getenv('NOTIFICATION_CHAT_ID')
        channel = getattr(settings, 'NOTIFICATION_CHANNEL_ID', None) or os.getenv('NOTIFICATION_CHANNEL_ID')
        parts = [p for p in [single, channel] if p]
        candidates = ','.join(parts)

    if not candidates:
        return []

    # Support comma/semicolon separated list
    raw_parts = [p for chunk in str(candidates).split(';') for p in chunk.split(',')]
    ids: List[Union[int, str]] = []
    for token in raw_parts:
        parsed = _parse_chat_id(token)
        if parsed != '':
            ids.append(parsed)
    return ids


async def _send_direct_message(chat_id: int | str, text: str, parse_mode: str = "HTML") -> None:
    """Send message via main bot instance if available; fallback to a temporary Bot."""
    try:
        # Try global bot instance first (more reliable within running loop)
        try:
            from bot import config as _config
            bot = getattr(_config, 'bot_instance', None)
        except Exception:
            bot = None

        if bot is not None:
            try:
                await bot.send_message(chat_id, text, parse_mode=parse_mode)
                return
            except Exception:
                # Fallback to temp bot
                pass

        temp_bot: Bot | None = None
        try:
            temp_bot = Bot(token=settings.TELEGRAM_BOT_TOKEN)
            await temp_bot.send_message(chat_id, text, parse_mode=parse_mode)
        finally:
            if temp_bot is not None:
                try:
                    await temp_bot.session.close()
                except Exception:
                    pass
    except Exception:
        # Swallow errors to avoid recursive logging
        pass


async def notify_error_text(text: str) -> None:
    chat_ids = _get_notification_chat_ids()
    if not chat_ids:
        return
    for chat_id in chat_ids:
        await _send_direct_message(chat_id, text, parse_mode="HTML")


def _build_message(lines: list[str]) -> str:
    safe_lines = [line for line in lines if line and line.strip()]
    return "\n".join(safe_lines)


async def _resolve_user_mention(user_id: Union[int, str]) -> str:
    try:
        tid = int(user_id)
    except Exception:
        return f"ID {user_id}"
    try:
        from users.models import User
        user = await User.objects.filter(telegram_id=tid).afirst()
        name = (user.name if user else None) or str(tid)
        username = name.strip()
        if not username:
            return f"ID {tid}"
        if not username.startswith('@'):
            username = f"@{username}"
        return username
    except Exception:
        return f"ID {tid}"


async def notify_user_command_error(user_id: int | str, command: str, human_message: str) -> None:
    mention = await _resolve_user_mention(user_id)
    text = _build_message([
        "🚨 <b>Ошибка</b>",
        f"👤 Пользователь: {mention}",
        f"🧩 Команда: <code>{command}</code>",
        f"❗ <b>Детали</b>: {human_message}",
    ])
    await notify_error_text(text)


async def notify_component_error(component: str, human_message: str) -> None:
    text = _build_message([
        "🚨 <b>Ошибка</b>",
        f"🧩 Компонент: {component}",
        f"❗ <b>Детали</b>: {human_message}",
    ])
    await notify_error_text(text)


async def notify_user_autobuy_error(user_id: int | str, stage: str, exc: Exception) -> None:
    mexc_hint = parse_mexc_error(exc)
    mention = await _resolve_user_mention(user_id)
    text = _build_message([
        "🚨 <b>Ошибка</b>",
        f"👤 Пользователь: {mention}",
        f"⚙️ Автобай: {stage}",
        f"❗ <b>Детали</b>: {mexc_hint}",
    ])
    await notify_error_text(text)


class TelegramErrorHandler(logging.Handler):
    """
    Logging handler that forwards ERROR/CRITICAL logs to Telegram notification chat.
    If running inside an event loop, schedules sending; otherwise, runs a short
    temporary loop to deliver the message.
    """

    def __init__(self) -> None:
        # Forward only ERROR and above to reduce noise
        super().__init__(level=logging.ERROR)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            chat_ids = _get_notification_chat_ids()
            if not chat_ids:
                return

            # Compose message; dedupe & guard conditions
            # 1) Only forward real exceptions
            if not record.exc_info:
                return

            # 2) Ignore technical log entries from bot_logging (command logs)
            pathname = getattr(record, 'pathname', '') or ''
            if 'bot_logging.py' in pathname:
                return

            # 3) Ignore synthetic messages like "Выполнил команду"
            raw_message = record.getMessage() or ''
            if 'Выполнил команду' in raw_message:
                return

            # Continue composing message
            user_id = getattr(record, 'user_id', None)
            component = self._detect_component(record)
            command = self._detect_command(record)
            # Try extract user id from message text if not provided
            if user_id is None:
                extracted = self._extract_user_id_from_message(record.getMessage())
                if extracted is not None:
                    user_id = extracted
            lines: list[str] = []
            if user_id is not None:
                # Will resolve mention in async sender
                lines.append("__USER_PLACEHOLDER__")
            else:
                lines.append("🚨 <b>Ошибка</b>")
                lines.append("🗂️ Тип: Общая")
            if command:
                lines.append(f"🧩 Команда: <code>{command}</code>")
            elif component:
                lines.append(f"🧩 Компонент: {component}")

            message_text = _sanitize_text(raw_message)

            # If exception, enrich message; prefer human-friendly MEXC hint if any
            if record.exc_info and record.exc_info[1]:
                try:
                    mexc_hint = parse_mexc_error(record.exc_info[1])
                    if mexc_hint and mexc_hint != str(record.exc_info[1]):
                        lines.append(mexc_hint)
                    else:
                        lines.append(message_text)
                except Exception:
                    lines.append(message_text)
            else:
                # Try to extract MEXC error code from message and map to friendly text
                try:
                    code_match = re.search(r'"code":\s*(\d+)', message_text)
                    if code_match:
                        code = int(code_match.group(1))
                        human = ERROR_MESSAGES.get(code)
                        if human:
                            lines.append(f"{human}")
                        else:
                            lines.append(message_text)
                    else:
                        lines.append(message_text)
                except Exception:
                    lines.append(message_text)

            text = _build_message(lines)

            async def _send():
                # Resolve mention if needed
                if "__USER_PLACEHOLDER__" in lines:
                    mention = await _resolve_user_mention(user_id)
                    header = _build_message([
                        "🚨 <b>Ошибка</b>",
                        f"👤 Пользователь: {mention}",
                    ])
                    final_lines = [header] + [ln for ln in lines if ln != "__USER_PLACEHOLDER__"]
                    final_text = _build_message(final_lines)
                else:
                    final_text = text

                # Deduplicate frequent identical messages
                if not _should_send(final_text):
                    return
                for chat_id in chat_ids:
                    await _send_direct_message(chat_id, final_text, parse_mode="HTML")

            try:
                loop = asyncio.get_running_loop()
                loop.create_task(_send())
            except RuntimeError:
                # No running loop in this thread; run synchronously
                asyncio.run(_send())

        except Exception:
            # Never raise from handler
            pass

    @staticmethod
    def _detect_component(record: logging.LogRecord) -> Optional[str]:
        pathname = getattr(record, 'pathname', '') or ''
        module_name = getattr(record, 'module', '') or ''

        if 'websocket_manager.py' in pathname or module_name == 'websocket_manager':
            return 'Вебсокет менеджере'
        if 'websocket_monitor.py' in pathname or module_name == 'websocket_monitor':
            return 'Вебсокет менеджере'
        if 'websocket_handlers.py' in pathname or module_name == 'websocket_handlers':
            return 'Вебсокет менеджере'
        if 'ws/market_stream.py' in pathname or module_name == 'market_stream':
            return 'В вебсокетах (рынок)'
        if 'ws/user_stream.py' in pathname or module_name == 'user_stream':
            return 'В вебсокетах (пользователь)'
        if 'autobuy.py' in pathname or module_name == 'autobuy':
            return 'цикле автобая'
        if 'trading.py' in pathname or module_name == 'trading':
            return 'командных обработчиках'
        return None

    @staticmethod
    def _detect_command(record: logging.LogRecord) -> Optional[str]:
        func = getattr(record, 'funcName', '') or ''
        # Common handlers mapping
        mapping = {
            'balance_handler': '/balance',
            'buy_handler': '/buy',
            'autobuy_handler': '/autobuy',
            'stop_autobuy': '/stop',
            'status_handler': '/status',
            'ask_stats_period': '/stats',
            'bot_start': '/start',
            'get_user_price': '/price',
        }
        return mapping.get(func)

    @staticmethod
    def _extract_user_id_from_message(message_text: str) -> Optional[int]:
        if not message_text:
            return None
        patterns = [
            r'пользовател[яе]\s+(\d+)',
            r'user\s+(\d+)',
            r'user_id\D+(\d+)',
            r'telegram_id\D+(\d+)',
            r'для\s+пользователя\s+(\d+)',
        ]
        for pat in patterns:
            m = re.search(pat, message_text, re.IGNORECASE)
            if m:
                try:
                    return int(m.group(1))
                except ValueError:
                    continue
        return None


# --- Helpers: sanitization and deduplication ---
_recent_messages: dict[str, float] = {}

def _should_send(text: str) -> bool:
    """Return True if this text hasn't been sent in the dedup window."""
    window = float(os.getenv('NOTIFY_DEDUP_SECONDS', '20'))
    if window <= 0:
        return True
    now = time.time()
    key = hashlib.sha256(text.encode('utf-8')).hexdigest()
    last = _recent_messages.get(key, 0)
    if now - last < window:
        return False
    _recent_messages[key] = now
    # Cleanup occasionally
    if len(_recent_messages) > 512:
        cutoff = now - window
        for k, ts in list(_recent_messages.items()):
            if ts < cutoff:
                _recent_messages.pop(k, None)
    return True


def _sanitize_text(text: str) -> str:
    """Mask sensitive tokens like signatures, API keys/secrets in messages."""
    if not text:
        return text
    # Mask signature=...
    text = re.sub(r'(signature=)[0-9a-fA-F]+', r'\1***', text)
    # Mask API key headers/fields
    text = re.sub(r'(X-MEXC-APIKEY[:=]\s*)([A-Za-z0-9_-]+)', r'\1***', text, flags=re.IGNORECASE)
    text = re.sub(r'("?api_key"?\s*[:=]\s*["\'])([^"\']+)(["\'])', r'\1***\3', text, flags=re.IGNORECASE)
    text = re.sub(r'("?apiSecret"?\s*[:=]\s*["\'])([^"\']+)(["\'])', r'\1***\3', text, flags=re.IGNORECASE)
    text = re.sub(r'("?api_secret"?\s*[:=]\s*["\'])([^"\']+)(["\'])', r'\1***\3', text, flags=re.IGNORECASE)
    return text


