import json
from datetime import datetime
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


def log_search(
    original_text: str,
    translated_text: str,
    api_data: dict,
    translation_provider: str = "unknown",
    translation_comparison: Optional[dict] = None,
):
    search_file = Path(SEARCH_LOG_FILE)
    key_data = extract_key_data(api_data)
    entry = {
        "timestamp": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"),
        "original_query": original_text,
        "translated_query": translated_text,
        "translation_provider": translation_provider,
        "translation_comparison": translation_comparison or {},
        "key_data": key_data,
        "aliexpress_data": api_data,
    }

    with open(search_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False))
        f.write("\n")

    # Also print structured logs for Railway runtime logs
    print("SEARCH_LOG:", json.dumps({
        "timestamp": entry["timestamp"],
        "original_query": original_text,
        "translated_query": translated_text,
        "translation_provider": translation_provider,
        "translation_comparison": translation_comparison or {},
        "key_data": key_data,
    }, ensure_ascii=False))
