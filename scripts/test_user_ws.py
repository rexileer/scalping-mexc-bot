import asyncio
import aiohttp
import json
import os
import sys
import time

# Add Django setup
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings")

import django
django.setup()


async def get_listen_key(api_key: str, api_secret: str):
    import hmac
    import hashlib
    import time as _t

    url = "https://api.mexc.com/api/v3/userDataStream"
    ts = int(_t.time() * 1000)
    query = f"timestamp={ts}"
    sig = hmac.new(api_secret.encode(), query.encode(), hashlib.sha256).hexdigest()
    request_url = f"{url}?{query}&signature={sig}"

    async with aiohttp.ClientSession() as session:
        async with session.post(request_url, headers={"X-MEXC-APIKEY": api_key, "Content-Type": "application/json"}) as resp:
            txt = await resp.text()
            if resp.status != 200:
                raise RuntimeError(f"listenKey error {resp.status}: {txt}")
            return json.loads(txt).get("listenKey")


async def run_test(api_key: str, api_secret: str, duration_sec: int = 120):
    listen_key = await get_listen_key(api_key, api_secret)
    ws_url = f"ws://wbs-api.mexc.com/ws?listenKey={listen_key}"

    async with aiohttp.ClientSession() as session:
        async with session.ws_connect(ws_url, heartbeat=None, compress=False) as ws:
            # subscribe to private orders + account
            params = [
                "spot@private.orders.v3.api.pb",
                "spot@private.account.v3.api.pb",
            ]
            sub_msg = {"method": "SUBSCRIPTION", "params": params, "id": int(time.time() * 1000)}
            await ws.send_str(json.dumps(sub_msg))
            print("[test] sent subscription", params)

            start = time.time()
            last_msg_at = start
            while time.time() - start < duration_sec:
                try:
                    msg = await ws.receive(timeout=15)
                except asyncio.TimeoutError:
                    print("[test] timeout waiting messages; sending ping")
                    try:
                        await ws.send_str(json.dumps({"method": "PING"}))
                    except Exception as e:
                        print("[test] ping failed:", e)
                        break
                    continue

                if msg.type == aiohttp.WSMsgType.TEXT:
                    data = msg.data
                    print("[test] TEXT:", data[:200])
                    last_msg_at = time.time()
                elif msg.type == aiohttp.WSMsgType.BINARY:
                    print("[test] BINARY:", len(msg.data), "bytes")
                    last_msg_at = time.time()
                elif msg.type == aiohttp.WSMsgType.CLOSED:
                    print("[test] CLOSED:", ws.close_code, msg.data)
                    break
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    print("[test] ERROR:", ws.exception())
                    break
                elif msg.type == aiohttp.WSMsgType.CLOSING:
                    print("[test] CLOSING...")
                    break

            print("[test] finished; last_msg_age_sec=", round(time.time() - last_msg_at, 1))


if __name__ == "__main__":
    # Usage: python scripts/test_user_ws.py <API_KEY> <API_SECRET> [duration_sec]
    if len(sys.argv) < 3:
        print("Usage: python scripts/test_user_ws.py <API_KEY> <API_SECRET> [duration_sec]")
        sys.exit(1)
    api_key = sys.argv[1]
    api_secret = sys.argv[2]
    duration = int(sys.argv[3]) if len(sys.argv) > 3 else 120
    asyncio.run(run_test(api_key, api_secret, duration))


