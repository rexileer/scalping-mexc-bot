from aiogram.fsm.state import State, StatesGroup

class APIAuth(StatesGroup):
    waiting_for_api_key = State()
    waiting_for_api_secret = State()
