import time
import hashlib
import os
import requests
import asyncio
import re

ALI_KEY = os.getenv("ALIEXPRESS_APP_KEY")
ALI_SECRET = os.getenv("ALIEXPRESS_APP_SECRET")

# Seconds to wait for any AliExpress API response.
ALI_API_TIMEOUT = 15


# Explicitly request all useful fields from the affiliate product query API,
# including lastest_volume which is the only sales-count field the API returns.
_PRODUCT_FIELDS = ",".join([
    "product_id",
    "product_title",
    "product_main_image_url",
    "product_small_image_urls",
    "product_detail_url",
    "promotion_link",
    "target_sale_price",
    "target_sale_price_currency",
    "target_original_price",
    "target_original_price_currency",
    "sale_price",
    "original_price_currency",
    "app_sale_price",
    "app_sale_price_currency",
    "evaluate_rate",
    "lastest_volume",
    "commission_rate",
    "discount",
    "shop_id",
    "shop_url",
    "first_level_category_id",
    "first_level_category_name",
    "second_level_category_id",
    "second_level_category_name",
    "platform_product_type",
])


def _add_tracking_id(params: dict) -> dict:
    """Attach the affiliate tracking ID (ALI_TRACKING_ID) if configured.
    tracking_id is an optional request parameter on product.query,
    product.smartmatch, hotproduct.query and productdetail.get; it ties the
    returned promotion_link to the affiliate account."""
    tracking_id = os.getenv("ALI_TRACKING_ID", "").strip()
    if tracking_id:
        params["tracking_id"] = tracking_id
    return params


def build_product_query_params(
    keywords: str,
    page_no: int = 1,
    page_size: int = 20,
    category_ids: str | None = None,
) -> dict:
    params = {
        "page_no": page_no,
        "page_size": page_size,
        "keywords": keywords,
    }

    # Locale params help with coverage for rating/price fields.
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

    if category_ids:
        params["category_ids"] = category_ids

    return _add_tracking_id(params)


def build_product_smartmatch_params(
    keywords: str,
    page_no: int = 1,
    page_size: int = 20,
    category_ids: str | None = None,
) -> dict:
    # Smartmatch shares the same locale/search parameters as product.query.
    return build_product_query_params(
        keywords=keywords,
        page_no=page_no,
        page_size=page_size,
        category_ids=category_ids,
    )


def build_hotproduct_query_params(
    page_no: int = 1,
    page_size: int = 20,
    category_ids: str | None = None,
    keywords: str | None = None,
) -> dict:
    params = {
        "page_no": page_no,
        "page_size": page_size,
        "fields": _PRODUCT_FIELDS,
        "platform_product_type": os.getenv("ALI_PLATFORM_PRODUCT_TYPE", "ALL"),
        "sort": os.getenv("ALI_HOTPRODUCT_SORT", "LAST_VOLUME_DESC"),
    }

    target_language = os.getenv("ALI_TARGET_LANGUAGE", "EN")
    target_currency = os.getenv("ALI_TARGET_CURRENCY", "USD")
    ship_to_country = os.getenv("ALI_SHIP_TO_COUNTRY", "US")

    if target_language:
        params["target_language"] = target_language
    if target_currency:
        params["target_currency"] = target_currency
    if ship_to_country:
        params["ship_to_country"] = ship_to_country

    if category_ids:
        params["category_ids"] = category_ids
    if keywords:
        params["keywords"] = keywords

    return _add_tracking_id(params)


def _to_bool(value: str | None) -> bool:
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "yes", "on"}


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

def api_timestamp() -> str:
    """Request timestamp as epoch milliseconds, like the official AliExpress SDK.
    The "YYYY-MM-DD HH:MM:SS" form is read by the gateway as GMT+8 (China time),
    so a UTC string is 8 hours off and the request is rejected."""
    return str(int(time.time() * 1000))


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
        "timestamp": api_timestamp(),
        "format": "json",
        "v": "2.0",
        "sign_method": "md5",
        **extra_params
    }
    params["sign"] = generate_signature(params, ALI_SECRET)
    try:
        resp = requests.get("https://api-sg.aliexpress.com/sync", params=params, timeout=ALI_API_TIMEOUT)
    except requests.RequestException as e:
        print(f"AliExpress API request error: {e}")
        return {"error": str(e)}
    try:
        return resp.json()
    except Exception as e:
        print(f"AliExpress API JSON parse error: {e}")
        return {}

async def call_aliexpress_sync_api(method: str, extra_params: dict):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, call_aliexpress_sync_api_sync, method, extra_params)


async def search_products_with_fallback(
    keywords: str,
    page_no: int = 1,
    page_size: int = 20,
    category_ids: str | None = None,
    force_query: bool = False,
) -> tuple[dict, str]:
    """Search products using configured strategy.

    Modes:
    - smartmatch: use smartmatch only
    - query: use product.query only
    - hybrid (default): smartmatch first, then product.query fallback
    """
    search_mode = os.getenv("ALI_SEARCH_MODE", "hybrid").strip().lower()

    smartmatch_params = build_product_smartmatch_params(
        keywords=keywords,
        page_no=page_no,
        page_size=page_size,
        category_ids=category_ids,
    )
    query_params = build_product_query_params(
        keywords=keywords,
        page_no=page_no,
        page_size=page_size,
        category_ids=category_ids,
    )

    if force_query:
        query_data = await call_aliexpress_sync_api("aliexpress.affiliate.product.query", query_params)
        return query_data, "aliexpress.affiliate.product.query"

    if search_mode == "smartmatch":
        smartmatch_data = await call_aliexpress_sync_api(
            "aliexpress.affiliate.product.smartmatch",
            smartmatch_params,
        )
        return smartmatch_data, "aliexpress.affiliate.product.smartmatch"

    if search_mode == "query":
        query_data = await call_aliexpress_sync_api("aliexpress.affiliate.product.query", query_params)
        return query_data, "aliexpress.affiliate.product.query"

    smartmatch_data = await call_aliexpress_sync_api(
        "aliexpress.affiliate.product.smartmatch",
        smartmatch_params,
    )
    smartmatch_products = find_products_in_response(smartmatch_data) or []
    if smartmatch_products:
        return smartmatch_data, "aliexpress.affiliate.product.smartmatch"

    query_data = await call_aliexpress_sync_api("aliexpress.affiliate.product.query", query_params)
    return query_data, "aliexpress.affiliate.product.query"


async def compare_search_methods(
    keywords: str,
    page_no: int = 1,
    page_size: int = 20,
    category_ids: str | None = None,
) -> dict:
    """Compare smartmatch and product.query responses for the same input.
    Returns count + sample titles for easier runtime verification."""
    smartmatch_params = build_product_smartmatch_params(
        keywords=keywords,
        page_no=page_no,
        page_size=page_size,
        category_ids=category_ids,
    )
    query_params = build_product_query_params(
        keywords=keywords,
        page_no=page_no,
        page_size=page_size,
        category_ids=category_ids,
    )

    smartmatch_data, query_data = await asyncio.gather(
        call_aliexpress_sync_api("aliexpress.affiliate.product.smartmatch", smartmatch_params),
        call_aliexpress_sync_api("aliexpress.affiliate.product.query", query_params),
    )

    smartmatch_products = find_products_in_response(smartmatch_data) or []
    query_products = find_products_in_response(query_data) or []

    def _sample_titles(products: list[dict], limit: int = 3) -> list[str]:
        titles = []
        for p in products[:limit]:
            t = p.get("title") or p.get("product_title") or p.get("productTitle") or ""
            if t:
                titles.append(str(t)[:120])
        return titles

    return {
        "keywords": keywords,
        "smartmatch_count": len(smartmatch_products),
        "query_count": len(query_products),
        "smartmatch_titles": _sample_titles(smartmatch_products),
        "query_titles": _sample_titles(query_products),
    }


async def fetch_hot_products(
    page_no: int = 1,
    page_size: int = 20,
    category_ids: str | None = None,
    keywords: str | None = None,
) -> tuple[dict, str]:
    params = build_hotproduct_query_params(
        page_no=page_no,
        page_size=page_size,
        category_ids=category_ids,
        keywords=keywords,
    )
    data = await call_aliexpress_sync_api("aliexpress.affiliate.hotproduct.query", params)
    return data, "aliexpress.affiliate.hotproduct.query"


def product_page_url(product: dict) -> str | None:
    """Plain (non-affiliate) product page URL."""
    url = product.get("product_detail_url")
    if url:
        return str(url).strip()
    pid = product.get("product_id")
    return f"https://www.aliexpress.com/item/{pid}.html" if pid else None


async def generate_affiliate_links(urls: list[str]) -> dict[str, str]:
    """Turn plain AliExpress URLs into affiliate links with
    aliexpress.affiliate.link.generate. Needs ALI_TRACKING_ID.
    Returns {source_url: promotion_link}; {} on failure."""
    tracking_id = os.getenv("ALI_TRACKING_ID", "").strip()
    if not urls or not tracking_id:
        if urls:
            print("ALI_TRACKING_ID is not set - cannot generate affiliate links")
        return {}

    data = await call_aliexpress_sync_api("aliexpress.affiliate.link.generate", {
        "source_values": ",".join(urls),
        "promotion_link_type": 0,
        "tracking_id": tracking_id,
    })
    error = get_api_error(data)
    if error:
        print(f"ALI_API_ERROR (link.generate): {error}")
        return {}

    links: dict[str, str] = {}
    try:
        result = data["aliexpress_affiliate_link_generate_response"]["resp_result"]["result"]
        items = result["promotion_links"]["promotion_link"]
    except (KeyError, TypeError):
        items = []
    for item in items or []:
        if isinstance(item, dict) and item.get("source_value") and item.get("promotion_link"):
            links[str(item["source_value"])] = str(item["promotion_link"])
    return links


_DETAIL_FIELDS = ",".join([
    "product_id",
    "evaluate_rate",
    "lastest_volume",
    "review_count",
    "trade_count",
    "average_star",
    "order_count",
    "sale_count",
    "product_title",
    "target_sale_price",
    "target_original_price",
    "product_main_image_url",
    "promotion_link",
])


def _fetch_product_details_sync(product_ids: list[str]) -> dict[str, dict]:
    """Call aliexpress.affiliate.productdetail.get for a batch of product IDs.
    Returns a mapping of product_id -> detail dict."""
    if not ALI_KEY or not ALI_SECRET or not product_ids:
        return {}

    params = {
        "app_key": ALI_KEY,
        "method": "aliexpress.affiliate.productdetail.get",
        "timestamp": api_timestamp(),
        "format": "json",
        "v": "2.0",
        "sign_method": "md5",
        "product_ids": ",".join(product_ids),
        "fields": _DETAIL_FIELDS,
        "target_currency": os.getenv("ALI_TARGET_CURRENCY", "USD"),
        "target_language": os.getenv("ALI_TARGET_LANGUAGE", "EN"),
    }
    _add_tracking_id(params)
    params["sign"] = generate_signature(params, ALI_SECRET)  # type: ignore[arg-type]

    try:
        resp = requests.get("https://api-sg.aliexpress.com/sync", params=params, timeout=ALI_API_TIMEOUT)
        data = resp.json()
    except Exception as e:
        print(f"AliExpress detail API error: {e}")
        return {}

    # Navigate into the response to find the product list
    products = find_products_in_response(data) or []
    result: dict[str, dict] = {}
    for p in products:
        pid = str(p.get("product_id", ""))
        if pid:
            result[pid] = p
    return result


async def enrich_products_with_details(products: list[dict]) -> list[dict]:
    """Fetch detail data for products that are missing review/trade counts
    and merge the extra fields into the existing product dicts."""
    missing_ids = [
        str(p.get("product_id", ""))
        for p in products
        if p.get("product_id")
        and pick_best_count(p, ["lastest_volume", "trade_count", "orders", "order_count",
                                 "sale_count", "sold_count", "volume"]) == 0
    ]

    if not missing_ids:
        return products

    loop = asyncio.get_running_loop()
    details = await loop.run_in_executor(None, _fetch_product_details_sync, missing_ids)

    if not details:
        return products

    for p in products:
        pid = str(p.get("product_id", ""))
        if pid in details:
            detail = details[pid]
            # Only overwrite fields that are currently None/missing
            for field in ["evaluate_rate", "lastest_volume", "review_count",
                          "trade_count", "average_star", "order_count", "sale_count"]:
                if p.get(field) is None and detail.get(field) is not None:
                    p[field] = detail[field]

    return products


def get_api_error(data) -> str | None:
    """Return a readable error if the API call failed, else None.

    Covers local failures ({"error": ...}), gateway errors
    ({"error_response": {...}}, e.g. bad signature/timestamp/app key) and
    resp_result with resp_code != 200."""
    if not data:
        return "empty response"
    if not isinstance(data, dict):
        return None
    if data.get("error"):
        return str(data["error"])
    err = data.get("error_response")
    if isinstance(err, dict):
        parts = [str(err.get(k)) for k in ("code", "msg", "sub_code", "sub_msg") if err.get(k)]
        return "error_response: " + " | ".join(parts) if parts else f"error_response: {err}"
    for value in data.values():
        if isinstance(value, dict) and isinstance(value.get("resp_result"), dict):
            resp = value["resp_result"]
            code = resp.get("resp_code")
            if code is not None and str(code) != "200":
                return f"resp_code {code}: {resp.get('resp_msg', '')}"
    return None


def _find_any_list(data):
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for value in data.values():
            if isinstance(value, list):
                return value
            if isinstance(value, dict):
                result = _find_any_list(value)
                if result:
                    return result
    return None


def find_products_in_response(data):
    """Return the product list from an affiliate API response, or None.

    Looks at the documented path first:
    <method>_response.resp_result.result.products.product
    and only falls back to the first list found anywhere."""
    if isinstance(data, dict):
        for value in data.values():
            if not isinstance(value, dict):
                continue
            try:
                products = value["resp_result"]["result"]["products"]
            except (KeyError, TypeError):
                continue
            if isinstance(products, dict):
                products = products.get("product")
            if isinstance(products, list):
                return products
    return _find_any_list(data)
