"""LLM gateway: dual-protocol (openai/anthropic) chat with failover and usage accounting.

- ``LLMGateway.chat()`` is the single entry point all other modules use.
- Failover semantics: network errors and HTTP 5xx move on to the next
  provider; HTTP 4xx is raised immediately (a configuration error must not
  silently switch routes).
- Every successful call is recorded in the ``llm_usage`` table. Accounting
  failures are logged but never break the main flow.
"""

from __future__ import annotations

import logging
from typing import Any, TypedDict

import httpx

from ..config import Settings
from ..db import get_conn

logger = logging.getLogger(__name__)

ANTHROPIC_VERSION = "2023-06-01"
_TIMEOUT = httpx.Timeout(120.0)


class LLMHTTPStatusError(Exception):
    """Non-retryable HTTP error (4xx) from a provider."""

    def __init__(self, provider: str, status_code: int, body: str):
        super().__init__(f"provider {provider!r}: HTTP {status_code}: {body}")
        self.provider = provider
        self.status_code = status_code
        self.body = body


class _RetryableError(Exception):
    """Network error or HTTP 5xx — worth trying the next provider."""


class Usage(TypedDict):
    input: int
    output: int


class LLMReply(TypedDict):
    text: str
    thinking: str
    provider: str
    model: str
    usage: Usage


def _coerce_tokens(value: Any) -> int:
    """Token counts may be missing or null; record 0 rather than fail."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


class LLMGateway:
    """Chat with configured LLM providers, failing over on transport/server errors."""

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or Settings.from_env()

    async def chat(
        self,
        messages: list[dict],
        tier: str = "fast",
        max_tokens: int = 4096,
        temperature: float | None = None,
    ) -> LLMReply:
        last_error: Exception | None = None
        for provider in self._ordered_providers(tier):
            try:
                reply = await self._call(provider, messages, max_tokens, temperature)
            except _RetryableError as exc:
                last_error = exc
                logger.warning(
                    "provider %s failed (%s); failing over to next provider",
                    provider.get("name"),
                    exc,
                )
                continue
            self._record_usage(reply, tier)
            return reply
        raise RuntimeError(f"all providers failed for tier {tier!r}") from last_error

    # -- provider ordering -------------------------------------------------

    def _ordered_providers(self, tier: str) -> list[dict]:
        if tier not in ("fast", "strong"):
            raise ValueError(f"unknown tier {tier!r}: expected 'fast' or 'strong'")
        providers = self.settings.llm_providers
        if not providers:
            raise RuntimeError("no llm providers configured")
        preferred = (
            self.settings.llm_strong if tier == "strong" else self.settings.llm_fast
        )
        head = [p for p in providers if p.get("name") == preferred]
        tail = [p for p in providers if p.get("name") != preferred]
        return head + tail

    # -- protocol dispatch -------------------------------------------------

    async def _call(
        self,
        provider: dict,
        messages: list[dict],
        max_tokens: int,
        temperature: float | None,
    ) -> LLMReply:
        protocol = str(provider.get("protocol", "openai")).lower()
        if protocol == "anthropic":
            return await self._call_anthropic(
                provider, messages, max_tokens, temperature
            )
        if protocol == "openai":
            return await self._call_openai(
                provider, messages, max_tokens, temperature
            )
        raise RuntimeError(
            f"provider {provider.get('name')!r}: unknown protocol {protocol!r}"
        )

    async def _call_openai(
        self,
        provider: dict,
        messages: list[dict],
        max_tokens: int,
        temperature: float | None,
    ) -> LLMReply:
        base = str(provider["base_url"]).rstrip("/")
        payload: dict[str, Any] = {
            "model": provider["model"],
            "messages": messages,
            "max_tokens": max_tokens,
        }
        if temperature is not None:
            payload["temperature"] = temperature
        headers = {
            "authorization": f"Bearer {provider['api_key']}",
            "content-type": "application/json",
        }
        data = await self._post(
            provider, f"{base}/chat/completions", headers, payload
        )
        choices = data.get("choices") or []
        text = ""
        if choices:
            text = choices[0].get("message", {}).get("content") or ""
        usage = data.get("usage") or {}
        return self._reply(
            provider,
            data,
            text=text,
            thinking="",
            input_tokens=usage.get("prompt_tokens"),
            output_tokens=usage.get("completion_tokens"),
        )

    async def _call_anthropic(
        self,
        provider: dict,
        messages: list[dict],
        max_tokens: int,
        temperature: float | None,
    ) -> LLMReply:
        base = str(provider["base_url"]).rstrip("/")
        payload: dict[str, Any] = {
            "model": provider["model"],
            "messages": messages,
            "max_tokens": max_tokens,
        }
        if temperature is not None:
            payload["temperature"] = temperature
        headers = {
            "x-api-key": provider["api_key"],
            "authorization": f"Bearer {provider['api_key']}",
            "anthropic-version": ANTHROPIC_VERSION,
            "content-type": "application/json",
        }
        data = await self._post(provider, f"{base}/v1/messages", headers, payload)
        blocks = [b for b in (data.get("content") or []) if isinstance(b, dict)]
        # Real responses lead with a thinking block; text is the LAST text block.
        text_blocks = [b.get("text", "") for b in blocks if b.get("type") == "text"]
        thinking_blocks = [
            b.get("thinking", "") for b in blocks if b.get("type") == "thinking"
        ]
        usage = data.get("usage") or {}
        return self._reply(
            provider,
            data,
            text=text_blocks[-1] if text_blocks else "",
            thinking="".join(thinking_blocks),
            input_tokens=usage.get("input_tokens"),
            output_tokens=usage.get("output_tokens"),
        )

    # -- HTTP transport ----------------------------------------------------

    async def _post(
        self, provider: dict, url: str, headers: dict, payload: dict
    ) -> dict:
        name = str(provider.get("name", "?"))
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.post(url, headers=headers, json=payload)
        except httpx.HTTPError as exc:
            raise _RetryableError(f"{name}: network error: {exc}") from exc
        if resp.status_code >= 500:
            raise _RetryableError(
                f"{name}: HTTP {resp.status_code}: {resp.text}"
            )
        if resp.status_code >= 400:
            raise LLMHTTPStatusError(name, resp.status_code, resp.text)
        return resp.json()

    # -- reply normalization -----------------------------------------------

    @staticmethod
    def _reply(
        provider: dict,
        data: dict,
        text: str,
        thinking: str,
        input_tokens: Any,
        output_tokens: Any,
    ) -> LLMReply:
        return LLMReply(
            text=text,
            thinking=thinking,
            provider=provider["name"],
            model=data.get("model") or provider["model"],
            usage=Usage(
                input=_coerce_tokens(input_tokens),
                output=_coerce_tokens(output_tokens),
            ),
        )

    # -- usage accounting ----------------------------------------------------

    def _record_usage(self, reply: LLMReply, tier: str) -> None:
        try:
            conn = get_conn(self.settings)
            try:
                conn.execute(
                    "INSERT INTO llm_usage"
                    " (provider, model, tier, prompt_tokens, completion_tokens)"
                    " VALUES (?, ?, ?, ?, ?)",
                    (
                        reply["provider"],
                        reply["model"],
                        tier,
                        reply["usage"]["input"],
                        reply["usage"]["output"],
                    ),
                )
                conn.commit()
            finally:
                conn.close()
        except Exception:
            logger.exception("llm_usage accounting failed; continuing anyway")
