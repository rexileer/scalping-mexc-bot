#!/usr/bin/env python3
import asyncio
import aiohttp
import json
import time
import hmac
import hashlib


async def get_listen_key(api_key: str, api_secret: str):
    url = "https://api.mexc.com/api/v3/userDataStream"
    ts = int(time.time() * 1000)
    query = f"timestamp={ts}"
    sig = hmac.new(api_secret.encode(), query.encode(), hashlib.sha256).hexdigest()
    request_url = f"{url}?{query}&signature={sig}"

    headers = {
        "X-MEXC-APIKEY": api_key,
        "Content-Type": "application/json"
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(request_url, headers=headers) as resp:
            txt = await resp.text()
            print(f"[test] listenKey response: {resp.status} - {txt}")
            if resp.status != 200:
                raise RuntimeError(f"listenKey error {resp.status}: {txt}")
            return json.loads(txt).get("listenKey")


async def run_test(api_key: str, api_secret: str, duration_sec: int = 120):
    print(f"[test] Starting test for {duration_sec} seconds...")
    
    try:
        listen_key = await get_listen_key(api_key, api_secret)
        print(f"[test] Got listenKey: {listen_key[:20]}...")
    except Exception as e:
        print(f"[test] Failed to get listenKey: {e}")
        return

    ws_url = f"ws://wbs-api.mexc.com/ws?listenKey={listen_key}"
    print(f"[test] Connecting to: {ws_url}")

    try:
        async with aiohttp.ClientSession() as session:
            async with session.ws_connect(ws_url, heartbeat=None, compress=False) as ws:
                print("[test] WebSocket connected successfully")
                
                # subscribe to private orders + account
                params = [
                    "spot@private.orders.v3.api.pb",
                    "spot@private.account.v3.api.pb",
                ]
                sub_msg = {"method": "SUBSCRIPTION", "params": params, "id": int(time.time() * 1000)}
                await ws.send_str(json.dumps(sub_msg))
                print(f"[test] sent subscription: {params}")

                start = time.time()
                last_msg_at = start
                msg_count = 0
                
                while time.time() - start < duration_sec:
                    try:
                        msg = await ws.receive(timeout=15)
                    except asyncio.TimeoutError:
                        print("[test] timeout waiting messages; sending ping")
                        try:
                            await ws.send_str(json.dumps({"method": "PING"}))
                        except Exception as e:
                            print(f"[test] ping failed: {e}")
                            break
                        continue

                    if msg.type == aiohttp.WSMsgType.TEXT:
                        data = msg.data
                        print(f"[test] TEXT ({len(data)} chars): {data[:200]}")
                        last_msg_at = time.time()
                        msg_count += 1
                    elif msg.type == aiohttp.WSMsgType.BINARY:
                        print(f"[test] BINARY: {len(msg.data)} bytes")
                        last_msg_at = time.time()
                        msg_count += 1
                    elif msg.type == aiohttp.WSMsgType.CLOSED:
                        print(f"[test] CLOSED: code={ws.close_code}, reason={msg.data}")
                        break
                    elif msg.type == aiohttp.WSMsgType.ERROR:
                        print(f"[test] ERROR: {ws.exception()}")
                        break
                    elif msg.type == aiohttp.WSMsgType.CLOSING:
                        print("[test] CLOSING...")
                        break

                print(f"[test] finished; messages={msg_count}, last_msg_age_sec={round(time.time() - last_msg_at, 1)}")
                
    except Exception as e:
        print(f"[test] Connection error: {e}")


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 3:
        print("Usage: python3 scripts/test_user_ws_simple.py <API_KEY> <API_SECRET> [duration_sec]")
        sys.exit(1)
        
    api_key = sys.argv[1]
    api_secret = sys.argv[2]
    duration = int(sys.argv[3]) if len(sys.argv) > 3 else 120
    
    print(f"[test] Testing API key: {api_key[:10]}...")
    asyncio.run(run_test(api_key, api_secret, duration))
