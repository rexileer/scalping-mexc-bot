import asyncio
import json
from logger import logger


async def ping_market_loop(ws):
    try:
        while not ws.closed:
            await asyncio.sleep(30)
            if ws.closed:
                break
            try:
                ping_message = {"method": "PING"}
                await ws.send_json(ping_message)
                # logger.info("[MarketWS] 📡 Sent PING (official format)")
            except Exception as e:
                logger.error(f"[MarketWS] Failed to send PING: {e}")
                break
    except asyncio.CancelledError:
        logger.debug("[MarketWS] Ping loop cancelled")
    except Exception as e:
        logger.error(f"[MarketWS] Ping loop error: {e}")


async def ping_user_loop(ws, user_id: int):
    try:
        while not ws.closed:
            await asyncio.sleep(30)
            if ws.closed:
                break
            try:
                ping_message = {"method": "PING"}
                await ws.send_str(json.dumps(ping_message))
                # logger.info(f"[UserWS] 📡 Sent PING (official format) to user {user_id}")
            except Exception as e:
                logger.error(f"[UserWS] Failed to send PING to user {user_id}: {e}")
                break
    except asyncio.CancelledError:
        logger.debug(f"[UserWS] Ping loop cancelled for user {user_id}")
    except Exception as e:
        logger.error(f"[UserWS] Ping loop error for user {user_id}: {e}")

