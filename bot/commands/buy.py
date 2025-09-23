import asyncio
from aiogram.types import Message
from asgiref.sync import sync_to_async
from django.utils import timezone
from users.models import Deal
from bot.logger import logger
from bot.utils.mexc import handle_mexc_response
from bot.utils.api_errors import parse_mexc_error
from mexc_sdk import Trade
from bot.constants import MAX_FAILS


async def monitor_order(message: Message, order_id: str, user_order_number: int):
    try:
        logger.info(f"Запуск мониторинга ордера {order_id} для пользователя {message.from_user.id}")
        deal = await sync_to_async(Deal.objects.get)(order_id=order_id)
        user = deal.user
        trade_client = Trade(api_key=user.api_key, api_secret=user.api_secret)
        symbol = user.pair.replace("/", "")
        fail_count = 0
    except Exception as e:
        logger.error(f"Ошибка при инициализации мониторинга: {e}")
        error_message = parse_mexc_error(e)
        user_message = f"❌ {error_message}"
        await message.answer('⚠️ Ошибка при инициализации мониторинга для ордера', parse_mode='HTML')
        await message.answer(user_message, parse_mode='HTML')
        return

    while True:
        try:
            order_status = trade_client.query_order(symbol, options={"orderId": order_id})
            handle_mexc_response(order_status, "Проверка ордера")
            status = order_status.get("status")

            if status == "CANCELED":
                deal.status = "CANCELED"
                deal.updated_at = timezone.now()
                await sync_to_async(deal.save)()
                await message.answer(
                    f"❌ <b>СДЕЛКА {user_order_number} ОТМЕНЕНА</b>\n\n"
                    f"🔁 Покупка: {deal.quantity:.6f} {deal.symbol[:3]} по {deal.buy_price:.6f} {deal.symbol[3:]}\n"
                    f"📈 Продажа: {deal.quantity:.6f} {deal.symbol[:3]} по {deal.sell_price:.6f} {deal.symbol[3:]}\n",
                    parse_mode='HTML'
                )
                return

            if status == "FILLED":
                deal.status = "FILLED"
                deal.updated_at = timezone.now()
                await sync_to_async(deal.save)()

                buy_total = deal.quantity * deal.buy_price
                sell_total = deal.quantity * deal.sell_price
                profit = sell_total - buy_total
                symbol = deal.symbol
                base = symbol[:3]
                quote = symbol[3:]

                text = (
                    f"✅ *СДЕЛКА {user_order_number} ЗАВЕРШЕНА*\n\n"
                    f"📦 Кол-во: `{deal.quantity:.6f}` {base}\n"
                    f"💰 Продано по: `{deal.sell_price:.6f}` {quote}\n"
                    f"📊 Прибыль: `{profit:.4f}` {quote}"
                )

                await message.answer(text, parse_mode='Markdown')
                return

            # Ордер ещё не исполнен
            fail_count = 0  # сбрасываем счётчик ошибок
            await asyncio.sleep(5)

        except asyncio.CancelledError:
            logger.info(f"Мониторинг ордера {order_id} отменён вручную")
            return
        except Exception as e:
            fail_count += 1
            logger.warning(f"Неудачная попытка мониторинга ордера {order_id} (попытка {fail_count}/{MAX_FAILS}): {e}")
            await asyncio.sleep(5)
            if fail_count >= MAX_FAILS:
                logger.error(f"Мониторинг ордера {order_id} остановлен после {MAX_FAILS} ошибок")
                error_message = parse_mexc_error(e)
                user_message = f"❌ {error_message}"
                await message.answer(f'⚠️ Ошибка при мониторинге ордера {user_order_number}', parse_mode='HTML')
                await message.answer(user_message, parse_mode='HTML')
                return