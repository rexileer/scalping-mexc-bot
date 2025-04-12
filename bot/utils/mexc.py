import hmac
import hashlib
import time
import requests

def check_mexc_keys(api_key: str, api_secret: str) -> bool:
    url = "https://api.mexc.com/api/v3/account"
    timestamp = int(time.time() * 1000)

    query_string = f"timestamp={timestamp}"
    signature = hmac.new(api_secret.encode(), query_string.encode(), hashlib.sha256).hexdigest()

    headers = {
        "X-MEXC-APIKEY": api_key
    }

    response = requests.get(f"{url}?{query_string}&signature={signature}", headers=headers)

    return response.status_code == 200
