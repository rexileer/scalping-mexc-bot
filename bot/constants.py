from django.conf import settings


PAYMENT_TIME = 30
PAYMENT_AMOUNT = 100
PAYMENT_WALLET = "TY43ubA82J5mrViFwAsNpNLkNLaj2rvx1Z"
PAYMENT_NETWORK = "TRC20"

DEFAULT_PAYMENT_MESSAGE = (
    f"🔒 Для получения доступа к боту на {PAYMENT_TIME} дней:\n\n"
    f"1️⃣ Оплатите {PAYMENT_AMOUNT} USDT в сети {PAYMENT_NETWORK} на кошелёк:\n"
    f"<code>{PAYMENT_WALLET}</code>\n\n"
    f"2️⃣ После оплаты отправьте скриншот и TXID в ЛС 👉 @TestScalpingBotSupport\n\n"
    f"Перед оплатой рекомендуем нажать /start для актуализации информации."
)

MONTHS_RU = {
    1: "Январь", 2: "Февраль", 3: "Март", 4: "Апрель",
    5: "Май", 6: "Июнь", 7: "Июль", 8: "Август",
    9: "Сентябрь", 10: "Октябрь", 11: "Ноябрь", 12: "Декабрь"
}

PAIR = settings.PAIR

MAX_FAILS = 5 # Максимальное количество неудачных попыток до остановки мониторинга