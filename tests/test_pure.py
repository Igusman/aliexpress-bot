import hashlib

import pytest

from handlers.messages import chunk_html_messages, pick_best_product_link
from services.aliexpress_api import (
    generate_signature,
    parse_metric_count,
    pick_best_rate,
)
from services.utils import match_search_words, search_relevance_score, tokenize


# generate_signature

def test_generate_signature_sorts_params_and_wraps_with_secret():
    params = {"b": "2", "a": "1", "method": "x"}
    expected = hashlib.md5("SECRETa1b2methodxSECRET".encode()).hexdigest().upper()
    assert generate_signature(params, "SECRET") == expected


def test_generate_signature_is_order_independent():
    assert generate_signature({"a": 1, "b": 2}, "s") == generate_signature({"b": 2, "a": 1}, "s")


# parse_metric_count

@pytest.mark.parametrize("value, expected", [
    (None, 0),
    (42, 42),
    (3.9, 3),
    ("1,234", 1234),
    ("2000+ sold", 2000),
    ("", 0),
    ("n/a", 0),
])
def test_parse_metric_count(value, expected):
    assert parse_metric_count(value) == expected


# pick_best_rate

@pytest.mark.parametrize("product, expected", [
    ({"evaluate_rate": "96.5%"}, 96.5),
    ({"evaluate_rate": "4.5"}, 90.0),   # 0-5 stars -> percent
    ({"evaluate_rate": "98"}, 98.0),
    ({"evaluate_rate": None, "avg_rating": "5"}, 100.0),
    ({"evaluate_rate": "bad", "score": "80"}, 80.0),
    ({}, 0.0),
])
def test_pick_best_rate(product, expected):
    assert pick_best_rate(product) == expected


# match_search_words / search_relevance_score

def test_match_search_words_threshold():
    words = tokenize("water bottle kids")
    assert match_search_words("Kids Water Bottle 500ml", words)
    assert match_search_words("Water Bottle Sports", words)       # 2/3 >= 0.5
    assert not match_search_words("Bottle opener", words)          # 1/3 < 0.5


def test_match_search_words_rejects_footwear_accessories():
    words = tokenize("shoes")
    assert match_search_words("Men Running Shoes Breathable", words)
    assert not match_search_words("Shoe Repair Patch Sticker", words)


def test_search_relevance_score():
    words = tokenize("water bottle")
    assert search_relevance_score("Water Bottle", words) == 100.0
    assert search_relevance_score("Bottle", words) == 50.0
    assert search_relevance_score("Anything", []) == 0.0


def test_search_relevance_score_footwear_penalizes_accessories():
    words = tokenize("shoes")
    assert search_relevance_score("Running Shoes", words) > search_relevance_score("Shoes Repair Kit", words)


# pick_best_product_link

def test_pick_best_product_link_prefers_promotion_link():
    p = {"promotion_link": "https://s.click.aliexpress.com/e/1", "product_detail_url": "https://www.aliexpress.com/item/1.html"}
    assert pick_best_product_link(p) == "https://s.click.aliexpress.com/e/1"


def test_pick_best_product_link_skips_generic_and_missing():
    p = {"promotion_link": "https://best.aliexpress.com/", "product_detail_url": "https://www.aliexpress.com/item/2.html"}
    assert pick_best_product_link(p) == "https://www.aliexpress.com/item/2.html"
    assert pick_best_product_link({"promotion_link": None, "url": "https://aliexpress.com/"}) == "N/A"
    assert pick_best_product_link({}) == "N/A"


# chunk_html_messages

def test_chunk_html_messages_joins_until_limit():
    assert chunk_html_messages(["aaa", "bbb"], limit=10) == ["aaa\n\nbbb"]
    assert chunk_html_messages(["aaaa", "bbbb"], limit=9) == ["aaaa", "bbbb"]


def test_chunk_html_messages_truncates_oversized_part():
    assert chunk_html_messages(["x" * 12, "y"], limit=5) == ["xxxxx", "y"]
    assert chunk_html_messages([]) == []


# find_products_in_response / get_api_error

from services.aliexpress_api import find_products_in_response, get_api_error  # noqa: E402

OK_RESPONSE = {
    "aliexpress_affiliate_product_query_response": {
        "resp_result": {
            "resp_code": 200,
            "resp_msg": "Call succeeds",
            "result": {"current_record_count": 1, "products": {"product": [{"product_id": 1}]}},
        },
        "request_id": "abc",
    }
}


def test_find_products_known_path():
    assert find_products_in_response(OK_RESPONSE) == [{"product_id": 1}]
    assert get_api_error(OK_RESPONSE) is None


def test_get_api_error_variants():
    gateway = {"error_response": {"code": "IncompleteSignature", "msg": "bad sign", "request_id": "1"}}
    assert find_products_in_response(gateway) is None
    assert "IncompleteSignature" in get_api_error(gateway)
    empty = {"x_response": {"resp_result": {"resp_code": 405, "resp_msg": "The result is empty"}}}
    assert get_api_error(empty) == "resp_code 405: The result is empty"
    assert get_api_error({"error": "timeout"}) == "timeout"
    assert get_api_error({}) == "empty response"


# discount_percent / rank_products / price_line

from handlers.messages import price_line  # noqa: E402
from services.utils import discount_percent, rank_products  # noqa: E402


def test_discount_percent():
    assert discount_percent({"discount": "35%"}) == 35.0
    assert discount_percent({"target_original_price": "10", "target_sale_price": "7.5"}) == 25.0
    assert discount_percent({"target_original_price": "5", "target_sale_price": "5"}) == 0.0
    assert discount_percent({}) == 0.0


def _p(name, relevance=100.0, rate=95.0, sales=100, **extra):
    return {"name": name, "__relevance": relevance, "__rate": rate, "__total_sales": sales, **extra}


def test_rank_products_relevance_first():
    ranked = rank_products([_p("half", relevance=50, sales=10000), _p("full", relevance=100, sales=5)])
    assert [p["name"] for p in ranked] == ["full", "half"]


def test_rank_products_prefers_rating_sales_discount_within_bucket():
    ranked = rank_products([
        _p("low-rated", rate=82, sales=100),
        _p("popular", rate=96, sales=5000),
        _p("unknown", rate=0, sales=0),
        _p("discounted", rate=96, sales=100, discount="60%"),
    ], min_rating=0)
    assert [p["name"] for p in ranked] == ["popular", "discounted", "low-rated", "unknown"]


def test_rank_products_drops_poor_ratings_only_if_enough_left():
    many = [_p(f"good{i}") for i in range(5)] + [_p("bad", rate=70)]
    assert "bad" not in [p["name"] for p in rank_products(many, min_rating=85)]
    few = [_p("good"), _p("bad", rate=70)]
    assert [p["name"] for p in rank_products(few, min_rating=85)] == ["good", "bad"]


def test_price_line_shows_discount():
    p = {"target_sale_price": "7.5", "target_original_price": "10", "target_sale_price_currency": "USD", "__discount": 25.0}
    assert price_line(p) == "7.5$ (במקום 10$, 25% הנחה)"
    assert price_line({"target_sale_price": "3", "target_sale_price_currency": "USD"}) == "3$"
