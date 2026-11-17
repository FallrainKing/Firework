"""Tests for the LLM gateway: dual protocol, thinking parsing, failover, usage accounting.

All HTTP traffic is mocked by patching ``httpx.AsyncClient.post`` — no real
API calls are ever made. Async gateway code is driven with ``asyncio.run``
(no pytest-asyncio dependency).
"""

import asyncio
import logging

import httpx
import pytest

from app.config import Settings
from app.db import get_conn
from app.llm.gateway import LLMGateway, LLMHTTPStatusError

ANTHROPIC_PROVIDER = {
    "name": "glm",
    "protocol": "anthropic",
    "base_url": "https://api.example.com",
    "api_key": "test-key",
    "model": "glm-5.3",
}

OPENAI_PROVIDER = {
    "name": "deepseek",
    "protocol": "openai",
    "base_url": "https://api.deepseek.example.com/v1",
    "api_key": "test-key",
    "model": "deepseek-v4-pro",
}


class FakeResponse:
    """Minimal stand-in for an httpx.Response."""

    def __init__(self, status_code=200, payload=None, text="", malformed=False):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.text = text
        self._malformed = malformed

    def json(self):
        if self._malformed:
            raise ValueError(f"malformed body: {self.text[:80]}")
        return self._payload


def patch_post(monkeypatch, responses):
    """Patch ``httpx.AsyncClient.post`` to yield the given responses in order.

    ``responses`` is a list whose items are either a ``FakeResponse`` (returned)
    or an ``Exception`` (raised, simulating a network error). Returns the list
    of captured calls as ``{"url": ..., "kwargs": ...}`` dicts.
    """
    calls = []

    async def fake_post(self, url, **kwargs):
        calls.append({"url": url, "kwargs": kwargs})
        item = responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    return calls


def make_settings(tmp_path, providers, fast="", strong=""):
    return Settings(
        data_dir=tmp_path / "data",
        qdrant_url="http://localhost:6333",
        llm_providers=providers,
        llm_fast=fast,
        llm_strong=strong,
    )


def test_thinking_block_returns_text(tmp_path, monkeypatch):
    # Ground truth: anthropic-protocol responses lead with a thinking block.
    payload = {
        "model": "glm-5.3",
        "content": [
            {"type": "thinking", "thinking": "let me think", "signature": "sig"},
            {"type": "text", "text": "ok"},
        ],
        "usage": {"input_tokens": 12, "output_tokens": 6},
    }
    calls = patch_post(monkeypatch, [FakeResponse(200, payload)])
    gw = LLMGateway(make_settings(tmp_path, [ANTHROPIC_PROVIDER], fast="glm"))

    reply = asyncio.run(gw.chat([{"role": "user", "content": "hi"}]))

    assert reply["text"] == "ok"
    assert reply["thinking"] == "let me think"
    assert reply["provider"] == "glm"
    assert reply["model"] == "glm-5.3"
    assert reply["usage"] == {"input": 12, "output": 6}
    # anthropic protocol details: url, headers, required max_tokens
    assert calls[0]["url"] == "https://api.example.com/v1/messages"
    headers = calls[0]["kwargs"]["headers"]
    assert headers["x-api-key"] == "test-key"
    assert headers["authorization"] == "Bearer test-key"
    assert headers["anthropic-version"] == "2023-06-01"
    assert calls[0]["kwargs"]["json"]["max_tokens"] == 4096


def test_openai_compat_parses_choice(tmp_path, monkeypatch):
    payload = {
        "model": "deepseek-v4-pro",
        "choices": [{"message": {"role": "assistant", "content": "hello"}}],
        "usage": {"prompt_tokens": 7, "completion_tokens": 3},
    }
    calls = patch_post(monkeypatch, [FakeResponse(200, payload)])
    gw = LLMGateway(make_settings(tmp_path, [OPENAI_PROVIDER], fast="deepseek"))

    reply = asyncio.run(gw.chat([{"role": "user", "content": "hi"}], max_tokens=512))

    assert reply["text"] == "hello"
    assert reply["thinking"] == ""
    assert reply["provider"] == "deepseek"
    assert reply["model"] == "deepseek-v4-pro"
    assert reply["usage"] == {"input": 7, "output": 3}
    assert calls[0]["url"] == "https://api.deepseek.example.com/v1/chat/completions"
    assert calls[0]["kwargs"]["json"]["max_tokens"] == 512


def test_failover_to_second_provider(tmp_path, monkeypatch):
    second = dict(ANTHROPIC_PROVIDER, name="second", model="m2")
    payload = {
        "model": "m2",
        "content": [{"type": "text", "text": "rescued"}],
        "usage": {"input_tokens": 1, "output_tokens": 1},
    }
    calls = patch_post(
        monkeypatch,
        [httpx.ConnectError("connection refused"), FakeResponse(200, payload)],
    )
    gw = LLMGateway(
        make_settings(tmp_path, [ANTHROPIC_PROVIDER, second], fast="glm")
    )

    reply = asyncio.run(gw.chat([{"role": "user", "content": "hi"}]))

    assert reply["provider"] == "second"
    assert reply["text"] == "rescued"
    assert len(calls) == 2  # first provider failed, second answered


def test_http_400_raises_without_failover(tmp_path, monkeypatch):
    # 4xx is a configuration error: it must surface, never silently switch routes.
    second = dict(ANTHROPIC_PROVIDER, name="second", model="m2")
    calls = patch_post(
        monkeypatch,
        [FakeResponse(400, text="invalid request")],
    )
    gw = LLMGateway(
        make_settings(tmp_path, [ANTHROPIC_PROVIDER, second], fast="glm")
    )

    with pytest.raises(LLMHTTPStatusError) as excinfo:
        asyncio.run(gw.chat([{"role": "user", "content": "hi"}]))

    assert excinfo.value.status_code == 400
    assert excinfo.value.provider == "glm"
    # only the preferred provider was hit; failover must NOT have happened
    assert [c["url"] for c in calls] == ["https://api.example.com/v1/messages"]


def test_429_fails_over_to_next_provider(tmp_path, monkeypatch):
    # 429 is transient (rate limit): switch routes instead of surfacing.
    second = dict(ANTHROPIC_PROVIDER, name="second", model="m2")
    payload = {
        "model": "m2",
        "content": [{"type": "text", "text": "rescued from rate limit"}],
        "usage": {"input_tokens": 1, "output_tokens": 1},
    }
    calls = patch_post(
        monkeypatch,
        [FakeResponse(429, text="rate limited"), FakeResponse(200, payload)],
    )
    gw = LLMGateway(
        make_settings(tmp_path, [ANTHROPIC_PROVIDER, second], fast="glm")
    )

    reply = asyncio.run(gw.chat([{"role": "user", "content": "hi"}]))

    assert reply["provider"] == "second"
    assert reply["text"] == "rescued from rate limit"
    assert len(calls) == 2  # 429 did NOT raise; the next provider answered


def test_html_body_with_200_fails_over(tmp_path, monkeypatch):
    # a 200 whose body is not JSON (e.g. an HTML error page from a broken
    # gateway) is as retryable as a 5xx: move on to the next provider.
    second = dict(ANTHROPIC_PROVIDER, name="second", model="m2")
    payload = {
        "model": "m2",
        "content": [{"type": "text", "text": "rescued from html"}],
        "usage": {"input_tokens": 1, "output_tokens": 1},
    }
    calls = patch_post(
        monkeypatch,
        [
            FakeResponse(200, text="<html>upstream error page</html>", malformed=True),
            FakeResponse(200, payload),
        ],
    )
    gw = LLMGateway(
        make_settings(tmp_path, [ANTHROPIC_PROVIDER, second], fast="glm")
    )

    reply = asyncio.run(gw.chat([{"role": "user", "content": "hi"}]))

    assert reply["provider"] == "second"
    assert reply["text"] == "rescued from html"
    assert len(calls) == 2


def test_empty_text_fails_over_to_next_provider(tmp_path, monkeypatch):
    # starved 200 (thinking ate the whole budget -> empty text block) must
    # NOT be returned as-is: it is as retryable as a 5xx.
    second = dict(ANTHROPIC_PROVIDER, name="second", model="m2")
    starved_payload = {
        "model": "glm-5.3",
        "content": [
            {"type": "thinking", "thinking": "long " * 5000, "signature": "sig"},
            {"type": "text", "text": ""},
        ],
        "usage": {"input_tokens": 10, "output_tokens": 2048},
    }
    payload = {
        "model": "m2",
        "content": [{"type": "text", "text": "rescued from starvation"}],
        "usage": {"input_tokens": 1, "output_tokens": 1},
    }
    calls = patch_post(
        monkeypatch,
        [FakeResponse(200, starved_payload), FakeResponse(200, payload)],
    )
    gw = LLMGateway(
        make_settings(tmp_path, [ANTHROPIC_PROVIDER, second], fast="glm")
    )

    reply = asyncio.run(gw.chat([{"role": "user", "content": "hi"}]))

    assert reply["provider"] == "second"
    assert reply["text"] == "rescued from starvation"
    assert len(calls) == 2  # starved 200 did not end the loop


def test_all_providers_empty_text_raises(tmp_path, monkeypatch):
    second = dict(ANTHROPIC_PROVIDER, name="second", model="m2")
    starved_payload = {
        "model": "glm-5.3",
        "content": [{"type": "text", "text": ""}],
        "usage": {"input_tokens": 10, "output_tokens": 2048},
    }
    starved_payload_2 = dict(starved_payload, model="m2")
    calls = patch_post(
        monkeypatch,
        [FakeResponse(200, starved_payload), FakeResponse(200, starved_payload_2)],
    )
    gw = LLMGateway(
        make_settings(tmp_path, [ANTHROPIC_PROVIDER, second], fast="glm")
    )

    with pytest.raises(RuntimeError, match="all providers returned empty text"):
        asyncio.run(gw.chat([{"role": "user", "content": "hi"}]))

    assert len(calls) == 2  # every provider got a chance before raising


def test_starved_call_still_records_usage(tmp_path, monkeypatch):
    # a starved-but-200 call consumed tokens: llm_usage must have a row
    # even though the call itself is treated as a retryable failure.
    starved_payload = {
        "model": "glm-5.3",
        "content": [{"type": "text", "text": ""}],
        "usage": {"input_tokens": 10, "output_tokens": 2048},
    }
    patch_post(monkeypatch, [FakeResponse(200, starved_payload)])
    settings = make_settings(tmp_path, [ANTHROPIC_PROVIDER], fast="glm", strong="glm")
    gw = LLMGateway(settings)

    with pytest.raises(RuntimeError):
        asyncio.run(gw.chat([{"role": "user", "content": "hi"}], tier="strong"))

    conn = get_conn(settings)
    try:
        rows = conn.execute(
            "SELECT provider, model, tier, prompt_tokens, completion_tokens"
            " FROM llm_usage"
        ).fetchall()
    finally:
        conn.close()
    assert len(rows) == 1
    row = rows[0]
    assert row["provider"] == "glm"
    assert row["model"] == "glm-5.3"
    assert row["tier"] == "strong"
    assert row["prompt_tokens"] == 10
    assert row["completion_tokens"] == 2048


def test_post_follows_redirects(tmp_path, monkeypatch):
    # httpx does NOT follow redirects by default; the gateway must opt in
    # so a provider answering a POST with a 3xx resolves instead of erroring.
    captured: dict = {}
    real_client = httpx.AsyncClient

    class CapturingClient(real_client):
        def __init__(self, **kwargs):
            captured.update(kwargs)
            super().__init__(**kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", CapturingClient)
    payload = {
        "model": "glm-5.3",
        "content": [{"type": "text", "text": "ok"}],
        "usage": {"input_tokens": 1, "output_tokens": 1},
    }
    patch_post(monkeypatch, [FakeResponse(200, payload)])
    gw = LLMGateway(make_settings(tmp_path, [ANTHROPIC_PROVIDER], fast="glm"))

    reply = asyncio.run(gw.chat([{"role": "user", "content": "hi"}]))

    assert reply["text"] == "ok"
    assert captured.get("follow_redirects") is True


def test_unknown_preferred_provider_warns_and_continues(tmp_path, monkeypatch, caplog):
    # a preferred name missing from LLM_PROVIDERS must not crash; it logs a
    # warning and chats with the configured providers.
    payload = {
        "model": "glm-5.3",
        "content": [{"type": "text", "text": "ok"}],
        "usage": {"input_tokens": 1, "output_tokens": 1},
    }
    patch_post(monkeypatch, [FakeResponse(200, payload)])
    gw = LLMGateway(
        make_settings(tmp_path, [ANTHROPIC_PROVIDER], fast="no-such-provider")
    )

    with caplog.at_level(logging.WARNING, logger="app.llm.gateway"):
        reply = asyncio.run(gw.chat([{"role": "user", "content": "hi"}]))

    assert reply["provider"] == "glm"  # chat still succeeded
    warnings = [r for r in caplog.records if "no-such-provider" in r.getMessage()]
    assert warnings, "a misconfigured preferred provider must be logged"


def test_text_before_thinking_takes_last_text(tmp_path, monkeypatch):
    payload = {
        "model": "glm-5.3",
        "content": [
            {"type": "text", "text": "first"},
            {"type": "thinking", "thinking": "hmm", "signature": "sig"},
            {"type": "text", "text": "second"},
        ],
        "usage": {"input_tokens": 5, "output_tokens": 5},
    }
    patch_post(monkeypatch, [FakeResponse(200, payload)])
    gw = LLMGateway(make_settings(tmp_path, [ANTHROPIC_PROVIDER], fast="glm"))

    reply = asyncio.run(gw.chat([{"role": "user", "content": "hi"}]))

    assert reply["text"] == "second"  # LAST text block wins
    assert reply["thinking"] == "hmm"


def test_usage_recorded_in_db(tmp_path, monkeypatch):
    payload = {
        "model": "glm-5.3",
        "content": [{"type": "text", "text": "ok"}],
        "usage": {"input_tokens": 21, "output_tokens": 9},
    }
    patch_post(monkeypatch, [FakeResponse(200, payload)])
    settings = make_settings(tmp_path, [ANTHROPIC_PROVIDER], fast="glm", strong="glm")
    gw = LLMGateway(settings)

    asyncio.run(gw.chat([{"role": "user", "content": "hi"}], tier="strong"))

    conn = get_conn(settings)
    try:
        rows = conn.execute(
            "SELECT provider, model, tier, prompt_tokens, completion_tokens"
            " FROM llm_usage"
        ).fetchall()
    finally:
        conn.close()
    assert len(rows) == 1
    row = rows[0]
    assert row["provider"] == "glm"
    assert row["model"] == "glm-5.3"
    assert row["tier"] == "strong"
    assert row["prompt_tokens"] == 21
    assert row["completion_tokens"] == 9
