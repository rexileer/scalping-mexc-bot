import time
from typing import Any, Dict, List


class PriceDirectionTracker:
    def __init__(self, max_history_size: int = 100) -> None:
        self.price_history: Dict[str, List[float]] = {}
        self.price_timestamps: Dict[str, List[float]] = {}
        self.is_rise: Dict[str, bool] = {}
        self.last_price_change: Dict[str, float] = {}
        self.max_history_size = max_history_size

    async def update(self, symbol: str, bid_price: float, ask_price: float) -> None:
        try:
            current_time = time.time()
            mid_price = (bid_price + ask_price) / 2

            if symbol not in self.price_history:
                self.price_history[symbol] = []
                self.price_timestamps[symbol] = []
                self.is_rise[symbol] = False
                self.last_price_change[symbol] = current_time

            self.price_history[symbol].append(mid_price)
            self.price_timestamps[symbol].append(current_time)

            if len(self.price_history[symbol]) > self.max_history_size:
                self.price_history[symbol] = self.price_history[symbol][-self.max_history_size :]
                self.price_timestamps[symbol] = self.price_timestamps[symbol][-self.max_history_size :]

            if len(self.price_history[symbol]) >= 2:
                current_price = self.price_history[symbol][-1]
                previous_price = self.price_history[symbol][-2]
                new_is_rise = current_price > previous_price
                if new_is_rise != self.is_rise[symbol]:
                    self.last_price_change[symbol] = current_time
                self.is_rise[symbol] = new_is_rise
        except Exception:
            # Silence tracking errors; not critical to main flow
            pass

    def get(self, symbol: str) -> Dict[str, Any]:
        if symbol not in self.is_rise:
            return {"is_rise": False, "last_change_time": 0, "current_price": 0, "price_history": []}
        current_price = 0
        if self.price_history.get(symbol):
            current_price = self.price_history[symbol][-1]
        return {
            "is_rise": self.is_rise[symbol],
            "last_change_time": self.last_price_change.get(symbol, 0),
            "current_price": current_price,
            "price_history": self.price_history.get(symbol, []),
        }

