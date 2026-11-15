import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

SEARCH_LOG_FILE = "search_log.txt"


def find_products_in_response(data):
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for _, value in data.items():
            if isinstance(value, list):
                return value
            if isinstance(value, dict):
                nested = find_products_in_response(value)
                if nested:
                    return nested
    return []


def extract_key_data(api_data: dict, limit: int = 5):
    products = find_products_in_response(api_data) or []
    key_products = []

    for p in products[:limit]:
        key_products.append({
            "title": p.get("title") or p.get("product_title") or p.get("productTitle"),
            "evaluate_rate": p.get("evaluate_rate"),
            "review_count": p.get("review_count"),
            "trade_count": p.get("trade_count"),
            "target_sale_price": p.get("target_sale_price"),
            "target_original_price": p.get("target_original_price"),
            "promotion_link": p.get("promotion_link"),
        })

    return {
        "products_found": len(products),
        "sample_products": key_products,
    }


def _log_to_file_enabled() -> bool:
    return os.getenv("SEARCH_LOG_TO_FILE", "0").strip().lower() in {"1", "true", "yes", "on"}


def log_search(
    original_text: str,
    translated_text: str,
    api_data: dict,
    translation_provider: str = "unknown",
    translation_comparison: Optional[dict] = None,
    search_method: str = "unknown",
    search_compare: Optional[dict] = None,
):
    entry = {
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "original_query": original_text,
        "translated_query": translated_text,
        "search_method": search_method,
        "search_compare": search_compare or {},
        "translation_provider": translation_provider,
        "translation_comparison": translation_comparison or {},
        "key_data": extract_key_data(api_data),
    }

    # Structured log line for Railway runtime logs.
    print("SEARCH_LOG:", json.dumps(entry, ensure_ascii=False))

    # Optional local file log (without the full raw API response).
    if _log_to_file_enabled():
        with open(Path(SEARCH_LOG_FILE), "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False))
            f.write("\n")
