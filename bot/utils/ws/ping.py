import asyncio
import json
from bot.logger import logger


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
            except (ConnectionResetError, ConnectionAbortedError, OSError) as e:
                # Connection closed - safe to break
                logger.debug(f"[MarketWS] Connection closed during PING: {e}")
                break
            except Exception as e:
                # Transient error - log but continue (don't kill loop)
                logger.warning(f"[MarketWS] Failed to send PING (will retry): {e}")
                await asyncio.sleep(5)  # Short pause before retry
    except asyncio.CancelledError:
        logger.debug("[MarketWS] Ping loop cancelled")
    except Exception as e:
        # Catch-all: log but don't re-raise to prevent loop death
        logger.error(
            f"[MarketWS] Ping loop fatal error (recovered): {e}", exc_info=True
        )


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
            except (ConnectionResetError, ConnectionAbortedError, OSError) as e:
                # Connection closed - safe to break
                logger.debug(
                    f"[UserWS] Connection closed during PING for user {user_id}: {e}"
                )
                break
            except Exception as e:
                # Transient error - log but continue (don't kill loop)
                logger.warning(
                    f"[UserWS] Failed to send PING to user {user_id} (will retry): {e}"
                )
                await asyncio.sleep(5)  # Short pause before retry
    except asyncio.CancelledError:
        logger.debug(f"[UserWS] Ping loop cancelled for user {user_id}")
    except Exception as e:
        # Catch-all: log but don't re-raise to prevent loop death
        logger.error(
            f"[UserWS] Ping loop fatal error for user {user_id} (recovered): {e}",
            exc_info=True,
        )
