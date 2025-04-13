from aiogram.fsm.state import State, StatesGroup

class APIAuth(StatesGroup):
    waiting_for_api_key = State()
    waiting_for_api_secret = State()

class ParameterChange(StatesGroup):
    waiting_for_profit = State()  # Ожидаем ввод прибыли
    waiting_for_pause = State()   # Ожидаем ввод паузы
    waiting_for_loss = State()    # Ожидаем ввод падения
    waiting_for_buy_amount = State()  # Ожидаем ввод cуммы
