"""Tests for the LLM gateway: dual protocol, thinking parsing, failover, usage accounting.

All HTTP traffic is mocked by patching ``httpx.AsyncClient.post`` — no real
API calls are ever made. Async gateway code is driven with ``asyncio.run``
(no pytest-asyncio dependency).
"""

import asyncio

import httpx

from app.config import Settings
from app.db import get_conn
from app.llm.gateway import LLMGateway

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

    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.text = text

    def json(self):
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
