import time
from typing import Any, Dict, List, Optional

# Protobuf generated wrappers
from bot.utils.websocket_pb import PushDataV3ApiWrapper_pb2
from bot.utils.websocket_pb import PublicAggreBookTickerV3Api_pb2  # noqa: F401  (imported for type visibility)
from bot.utils.websocket_pb import PublicAggreDealsV3Api_pb2  # noqa: F401
from bot.utils.websocket_pb import PrivateOrdersV3Api_pb2  # noqa: F401
from bot.utils.websocket_pb import PrivateAccountV3Api_pb2  # noqa: F401


def _map_bookticker(pb_obj) -> Dict[str, Any]:
    return {
        "publicbookticker": {
            # use lower-case keys as expected by existing code
            "bidprice": getattr(pb_obj, "bidPrice", ""),
            "askprice": getattr(pb_obj, "askPrice", ""),
            "bidquantity": getattr(pb_obj, "bidQuantity", ""),
            "askquantity": getattr(pb_obj, "askQuantity", ""),
        }
    }


def _map_deals(pb_obj) -> Dict[str, Any]:
    deals_list: List[Dict[str, Any]] = []
    for item in getattr(pb_obj, "deals", []):
        deals_list.append(
            {
                # prefer full names to align with current handler usage
                "price": getattr(item, "price", ""),
                "quantity": getattr(item, "quantity", ""),
                "tradeType": getattr(item, "tradeType", 0),
                "time": getattr(item, "time", 0),
            }
        )
    return {"publicdeals": {"dealsList": deals_list, "eventType": getattr(pb_obj, "eventType", "")}}


def _map_private_orders(pb_obj) -> Dict[str, Any]:
    # Map to short keys used across the project inside data['d']
    mapped: Dict[str, Any] = {
        "i": getattr(pb_obj, "id", ""),
        "c": getattr(pb_obj, "clientId", ""),
        "p": getattr(pb_obj, "price", ""),
        "q": getattr(pb_obj, "quantity", ""),
        "ap": getattr(pb_obj, "avgPrice", ""),
        "ot": getattr(pb_obj, "orderType", 0),
        "tt": getattr(pb_obj, "tradeType", 0),
        "m": getattr(pb_obj, "isMaker", False),
        "rqa": getattr(pb_obj, "remainQuantity", ""),
        "s": getattr(pb_obj, "status", 0),
        "ct": getattr(pb_obj, "createTime", 0),
    }
    # Include also verbose keys for potential future usage
    mapped.update(
        {
            "id": getattr(pb_obj, "id", ""),
            "clientId": getattr(pb_obj, "clientId", ""),
            "price": getattr(pb_obj, "price", ""),
            "quantity": getattr(pb_obj, "quantity", ""),
            "avgPrice": getattr(pb_obj, "avgPrice", ""),
            "orderType": getattr(pb_obj, "orderType", 0),
            "tradeType": getattr(pb_obj, "tradeType", 0),
            "isMaker": getattr(pb_obj, "isMaker", False),
            "remainQuantity": getattr(pb_obj, "remainQuantity", ""),
            "status": getattr(pb_obj, "status", 0),
            "createTime": getattr(pb_obj, "createTime", 0),
            "market": getattr(pb_obj, "market", ""),
        }
    )
    return {"d": mapped}


def _map_private_account(pb_obj) -> Dict[str, Any]:
    # Short keys to match existing handler expectations
    mapped: Dict[str, Any] = {
        "a": getattr(pb_obj, "vcoinName", ""),
        "f": getattr(pb_obj, "balanceAmount", ""),
        "l": getattr(pb_obj, "frozenAmount", ""),
        "t": getattr(pb_obj, "time", 0),
    }
    # Also include verbose
    mapped.update(
        {
            "vcoinName": getattr(pb_obj, "vcoinName", ""),
            "balanceAmount": getattr(pb_obj, "balanceAmount", ""),
            "frozenAmount": getattr(pb_obj, "frozenAmount", ""),
            "balanceAmountChange": getattr(pb_obj, "balanceAmountChange", ""),
            "frozenAmountChange": getattr(pb_obj, "frozenAmountChange", ""),
            "type": getattr(pb_obj, "type", ""),
            "time": getattr(pb_obj, "time", 0),
        }
    )
    return {"d": mapped}


def decode_push_message(binary_message: bytes) -> Optional[Dict[str, Any]]:
    """
    Decode Mexc protobuf push message into a dict compatible with existing JSON handlers.

    Returns a dict containing at minimum:
    - 'channel' and 'c'
    - 'symbol' and 's' (if available)
    - 'sendtime' and 't' (if available)
    - one of payload keys depending on channel: 'publicbookticker', 'publicdeals', or 'd' for private streams
    """
    try:
        wrapper = PushDataV3ApiWrapper_pb2.PushDataV3ApiWrapper()
        wrapper.ParseFromString(binary_message)

        channel = getattr(wrapper, "channel", "")
        symbol = getattr(wrapper, "symbol", "")
        send_time = getattr(wrapper, "sendTime", 0)

        result: Dict[str, Any] = {
            "channel": channel,
            "c": channel,
            "symbol": symbol,
            "s": symbol,
            "sendtime": send_time if send_time else int(time.time() * 1000),
            "t": send_time if send_time else int(time.time() * 1000),
        }

        # Public streams
        if wrapper.HasField("publicAggreBookTicker") or wrapper.HasField("publicBookTicker"):
            # Prefer aggre if present; both map to same structure for our needs
            payload = (
                getattr(wrapper, "publicAggreBookTicker")
                if wrapper.HasField("publicAggreBookTicker")
                else getattr(wrapper, "publicBookTicker")
            )
            result.update(_map_bookticker(payload))
            return result

        if wrapper.HasField("publicAggreDeals") or wrapper.HasField("publicDeals"):
            payload = (
                getattr(wrapper, "publicAggreDeals")
                if wrapper.HasField("publicAggreDeals")
                else getattr(wrapper, "publicDeals")
            )
            result.update(_map_deals(payload))
            return result

        # Private streams
        if wrapper.HasField("privateOrders"):
            result.update(_map_private_orders(getattr(wrapper, "privateOrders")))
            return result

        if wrapper.HasField("privateAccount"):
            result.update(_map_private_account(getattr(wrapper, "privateAccount")))
            return result

        # Other channels can be added as needed
        return result

    except Exception:
        # If decoding fails, return None so caller can ignore or log
        return None

