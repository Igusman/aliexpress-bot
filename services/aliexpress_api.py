import time
import hashlib
import os
import requests
import asyncio
import re

ALI_KEY = os.getenv("ALIEXPRESS_APP_KEY")
ALI_SECRET = os.getenv("ALIEXPRESS_APP_SECRET")


def build_product_query_params(keywords: str, page_no: int = 1, page_size: int = 20) -> dict:
    params = {
        "page_no": page_no,
        "page_size": page_size,
        "keywords": keywords,
    }

    # Locale params usually help with better coverage for rating/order fields.
    target_language = os.getenv("ALI_TARGET_LANGUAGE", "EN")
    target_currency = os.getenv("ALI_TARGET_CURRENCY", "USD")
    ship_to_country = os.getenv("ALI_SHIP_TO_COUNTRY", "US")

    if target_language:
        params["target_language"] = target_language
    if target_currency:
        params["target_currency"] = target_currency
    if ship_to_country:
        params["ship_to_country"] = ship_to_country

    sort_by = os.getenv("ALI_SORT_BY", "")
    if sort_by:
        params["sort"] = sort_by

    return params


def parse_metric_count(value) -> int:
    if value is None:
        return 0
    if isinstance(value, (int, float)):
        return int(value)

    cleaned = re.sub(r"[^0-9]", "", str(value))
    return int(cleaned) if cleaned else 0


def pick_best_count(product: dict, keys: list[str]) -> int:
    for key in keys:
        count = parse_metric_count(product.get(key))
        if count > 0:
            return count
    return 0


def pick_best_rate(product: dict) -> float:
    candidates = [
        product.get("evaluate_rate"),
        product.get("rating"),
        product.get("avg_rating"),
        product.get("score"),
    ]

    for value in candidates:
        if value is None:
            continue
        text = str(value).strip()
        try:
            if text.endswith("%"):
                return float(text.replace("%", ""))

            # Some APIs return 0-5 stars. Convert to percent for consistent sorting/display.
            score = float(text)
            if 0 <= score <= 5:
                return round((score / 5.0) * 100, 2)
            return score
        except (ValueError, TypeError):
            continue

    return 0.0

def generate_signature(params: dict, app_secret: str) -> str:
    sorted_params = ''.join([f"{k}{v}" for k, v in sorted(params.items())])
    base_string = f"{app_secret}{sorted_params}{app_secret}"
    return hashlib.md5(base_string.encode()).hexdigest().upper()

def call_aliexpress_sync_api_sync(method: str, extra_params: dict):
    if not ALI_KEY or not ALI_SECRET:
        return {
            "error": "ALIEXPRESS_APP_KEY or ALIEXPRESS_APP_SECRET is not set"
        }

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
    except Exception as e:
        print(f"AliExpress API JSON parse error: {e}")
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
