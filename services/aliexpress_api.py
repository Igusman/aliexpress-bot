import time
import hashlib
import os
import requests
import asyncio

ALI_KEY = os.getenv("ALIEXPRESS_APP_KEY")
ALI_SECRET = os.getenv("ALIEXPRESS_APP_SECRET")

def generate_signature(params: dict, app_secret: str) -> str:
    sorted_params = ''.join([f"{k}{v}" for k, v in sorted(params.items())])
    base_string = f"{app_secret}{sorted_params}{app_secret}"
    return hashlib.md5(base_string.encode()).hexdigest().upper()

def call_aliexpress_sync_api_sync(method: str, extra_params: dict):
    params = {
        "app_key": ALI_KEY,
        "method": method,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()),
        "format": "json",
        "v": "2.0",
        "sign_method": "md5",
        **extra_params
    }
    params["sign"] = generate_signature(params, ALI_SECRET)
    resp = requests.get("https://api-sg.aliexpress.com/sync", params=params)
    try:
        return resp.json()
    except:
        return {}

async def call_aliexpress_sync_api(method: str, extra_params: dict):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, call_aliexpress_sync_api_sync, method, extra_params)

def find_products_in_response(data):
    if isinstance(data, list): return data
    if isinstance(data, dict):
        for key, value in data.items():
            if isinstance(value, list): return value
            elif isinstance(value, dict):
                result = find_products_in_response(value)
                if result: return result
    return None
