import asyncio

import pytest

import services.translation as t


@pytest.fixture(autouse=True)
def clean_state(monkeypatch):
    t._cache.clear()
    t._cooldown_until.clear()
    monkeypatch.delenv("TRANSLATION_PROVIDER", raising=False)


def _fake_providers(monkeypatch, behavior):
    calls = []

    def fake(provider, text, source, target):
        calls.append(provider)
        result = behavior[provider]
        if isinstance(result, Exception):
            raise result
        return result(text)

    monkeypatch.setattr(t, "_translate_with_provider", fake)
    return calls


def test_falls_back_to_mymemory_and_skips_rate_limited_google(monkeypatch):
    calls = _fake_providers(monkeypatch, {
        "google": RuntimeError("You made too many requests to the server"),
        "mymemory": lambda text: "MM:" + text,
        "chatgpt": lambda text: "GPT:" + text,
    })
    assert asyncio.run(t.translate("a", "en", "he")) == ("MM:a", "mymemory")
    assert asyncio.run(t.translate("b", "en", "he")) == ("MM:b", "mymemory")
    assert calls == ["google", "mymemory", "mymemory"]  # google in cooldown for the 2nd call


def test_cache_avoids_repeat_requests(monkeypatch):
    calls = _fake_providers(monkeypatch, {"google": lambda text: "G:" + text, "mymemory": None, "chatgpt": None})
    asyncio.run(t.translate("x", "en", "he"))
    asyncio.run(t.translate("x", "en", "he"))
    assert calls == ["google"]


def test_all_providers_fail(monkeypatch):
    err = RuntimeError("down")
    _fake_providers(monkeypatch, {"google": err, "mymemory": err, "chatgpt": err})
    assert asyncio.run(t.translate("x", "he", "en")) == ("", "none")


def test_translate_titles_single_request(monkeypatch):
    calls = _fake_providers(monkeypatch, {
        "google": lambda text: "\n".join("HE " + line for line in text.split("\n")),
        "mymemory": None, "chatgpt": None,
    })
    assert asyncio.run(t.translate_titles_to_hebrew(["a b", "c"])) == ["HE a b", "HE c"]
    assert calls == ["google"]


def test_translate_titles_falls_back_one_by_one_on_line_mismatch(monkeypatch):
    _fake_providers(monkeypatch, {
        "google": lambda text: "merged" if "\n" in text else "HE " + text,
        "mymemory": None, "chatgpt": None,
    })
    assert asyncio.run(t.translate_titles_to_hebrew(["a", "b"])) == ["HE a", "HE b"]
