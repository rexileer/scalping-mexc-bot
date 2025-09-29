import asyncio
import aiohttp
import hmac
import hashlib
import time
from typing import Dict, Any, Optional
from urllib.parse import urlencode, quote


class MexcRestClient:
    """Minimal MEXC Spot v3 REST client (async), signed endpoints included."""

    BASE_URL = "https://api.mexc.com"

    def __init__(self, api_key: str, api_secret: str):
        self.api_key = api_key
        self.api_secret = api_secret
        self._time_offset_ms: Optional[int] = None
        self._last_time_sync: float = 0.0
        self._time_sync_interval_sec: int = 300

    async def _server_time(self) -> int:
        timeout = aiohttp.ClientTimeout(total=10)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(f"{self.BASE_URL}/api/v3/time") as resp:
                    data = await resp.json(content_type=None)
                    return int(data.get("serverTime", int(time.time() * 1000)))
        except Exception:
            # Fallback to local timestamp on timeout/network errors
            return int(time.time() * 1000)

    async def _ensure_time_offset(self) -> None:
        now = time.time()
        if (
            self._time_offset_ms is None
            or (now - self._last_time_sync) > self._time_sync_interval_sec
        ):
            server_ms = await self._server_time()
            local_ms = int(now * 1000)
            self._time_offset_ms = server_ms - local_ms
            self._last_time_sync = now

    async def _request(
        self,
        method: str,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        signed: bool = False,
        timeout_sec: int = 20,
        recv_window_ms: int = 59000,
    ) -> Dict[str, Any]:
        params = params.copy() if params else {}
        headers = {}

        if signed:
            # Keep client clock aligned and honor recvWindow
            await self._ensure_time_offset()
            server_ts = int(time.time() * 1000 + (self._time_offset_ms or 0))
            sign_params = params.copy()
            # stringify values to be safe
            for k, v in list(sign_params.items()):
                if isinstance(v, (float, int)):
                    sign_params[k] = str(v)
            if "recvWindow" not in sign_params and recv_window_ms:
                # Clamp to allowed maximum (< 60000)
                if int(recv_window_ms) >= 60000:
                    recv_window_ms = 59000
                sign_params["recvWindow"] = str(recv_window_ms)
            sign_base = urlencode(sign_params, quote_via=quote)
            to_sign = (
                f"{sign_base}&timestamp={server_ts}"
                if sign_base
                else f"timestamp={server_ts}"
            )
            signature = hmac.new(
                self.api_secret.encode(), to_sign.encode(), hashlib.sha256
            ).hexdigest()

            # final query params include original params + timestamp + signature
            params = sign_params
            params["timestamp"] = server_ts
            params["signature"] = signature
            headers["x-mexc-apikey"] = self.api_key
            headers["Content-Type"] = "application/json"

        url = f"{self.BASE_URL}{path}"
        timeout = aiohttp.ClientTimeout(total=timeout_sec)
        max_retries = 3
        backoff = 0.5
        last_err = None
        for _ in range(max_retries):
            try:
                async with aiohttp.ClientSession(
                    timeout=timeout,
                    connector=aiohttp.TCPConnector(
                        limit=100, limit_per_host=10, enable_cleanup_closed=True
                    ),
                ) as session:
                    if method == "GET":
                        async with session.get(
                            url, params=params, headers=headers
                        ) as resp:
                            data = await resp.json(content_type=None)
                            if resp.status != 200:
                                # If timestamp window error, resync time and retry
                                if (
                                    isinstance(data, dict)
                                    and data.get("code") == 700003
                                ):
                                    self._last_time_sync = 0.0
                                    await self._ensure_time_offset()
                                    raise aiohttp.ServerDisconnectedError()
                                raise RuntimeError(data)
                            return data
                    elif method == "POST":
                        if signed:
                            # Send with params in query (no body) per official examples
                            async with session.post(
                                url, params=params, headers=headers
                            ) as resp:
                                data = await resp.json(content_type=None)
                                if resp.status != 200:
                                    if (
                                        isinstance(data, dict)
                                        and data.get("code") == 700003
                                    ):
                                        self._last_time_sync = 0.0
                                        await self._ensure_time_offset()
                                        raise aiohttp.ServerDisconnectedError()
                                    raise RuntimeError(data)
                                return data
                        # Unsigned POST (rare): send JSON
                        async with session.post(
                            url, json=params, headers=headers
                        ) as resp:
                            data = await resp.json(content_type=None)
                            if resp.status != 200:
                                if (
                                    isinstance(data, dict)
                                    and data.get("code") == 700003
                                ):
                                    self._last_time_sync = 0.0
                                    await self._ensure_time_offset()
                                    raise aiohttp.ServerDisconnectedError()
                                raise RuntimeError(data)
                            return data
                    else:
                        raise ValueError("Unsupported method")
            except (
                aiohttp.ClientConnectorError,
                aiohttp.ClientOSError,
                aiohttp.ServerDisconnectedError,
                asyncio.TimeoutError,
            ) as e:
                last_err = e
                await asyncio.sleep(backoff)
                backoff *= 2
                continue
        if last_err:
            raise last_err

    # Public
    async def ticker_price(self, symbol: str) -> Dict[str, Any]:
        return await self._request(
            "GET",
            "/api/v3/ticker/price",
            {"symbol": symbol},
            signed=False,
            timeout_sec=10,
        )

    # Signed
    async def account_info(self) -> Dict[str, Any]:
        return await self._request(
            "GET", "/api/v3/account", {}, signed=True, timeout_sec=20
        )

    async def open_orders(self, symbol: str) -> Any:
        return await self._request(
            "GET", "/api/v3/openOrders", {"symbol": symbol}, signed=True, timeout_sec=20
        )

    async def new_order(
        self, symbol: str, side: str, order_type: str, options: Dict[str, Any]
    ) -> Dict[str, Any]:
        params = {"symbol": symbol, "side": side, "type": order_type}
        params.update(options or {})
        return await self._request(
            "POST", "/api/v3/order", params, signed=True, timeout_sec=25
        )

    async def query_order(self, symbol: str, options: Dict[str, Any]) -> Dict[str, Any]:
        params = {"symbol": symbol}
        params.update(options or {})
        return await self._request(
            "GET", "/api/v3/order", params, signed=True, timeout_sec=20
        )
