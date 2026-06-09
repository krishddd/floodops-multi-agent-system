"""
Provider-agnostic LLM backends for FloodOps.

Defines a small ``LLMProvider`` protocol and two concrete backends —
``AnthropicProvider`` (Claude) and ``GeminiProvider`` (Google) — plus a
``NullProvider`` that degrades gracefully when no API key is configured.

Design goals:
  * **No hard SDK dependency.** Both SDKs are imported lazily inside the
    provider, so the module imports fine with neither installed.
  * **Key added later.** ``make_provider()`` reads config/env at call time;
    until a key is set, ``available()`` is False and callers fall back to
    their deterministic mock paths.
  * **Structured output.** ``generate_structured()`` returns a validated
    Pydantic model instance (or ``None`` if unavailable), so agents can
    request typed reasoning without parsing.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional, Protocol, TypeVar, runtime_checkable

from pydantic import BaseModel

from floodops.config import (
    ANTHROPIC_API_KEY,
    ANTHROPIC_EFFORT,
    ANTHROPIC_MODEL,
    FLOODOPS_LLM_PROVIDER,
    GEMINI_MODEL,
    GOOGLE_GENAI_API_KEY,
)

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


@runtime_checkable
class LLMProvider(Protocol):
    """Minimal interface every backend implements."""

    name: str

    def available(self) -> bool:
        """True when a key + SDK are present and calls can be made."""
        ...

    async def generate(self, prompt: str, system: Optional[str] = None) -> str:
        """Return free-text completion."""
        ...

    async def generate_structured(
        self, prompt: str, schema: type[T], system: Optional[str] = None
    ) -> Optional[T]:
        """Return a validated instance of ``schema``, or None if unavailable."""
        ...


def _extract_json(text: str) -> Optional[dict[str, Any]]:
    """Best-effort extraction of the first JSON object from a text blob."""
    if not text:
        return None
    # Fast path
    try:
        return json.loads(text)
    except Exception:
        pass
    # Find the outermost {...} block
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except Exception:
            return None
    return None


class NullProvider:
    """No-op provider used when no key/SDK is configured.

    ``available()`` is False so every reasoning helper falls back to its
    deterministic mock value. ``generate()`` returns a clearly-labelled
    placeholder so demos still render something.
    """

    name = "null"

    def available(self) -> bool:
        return False

    async def generate(self, prompt: str, system: Optional[str] = None) -> str:
        return (
            "[LLM disabled — set ANTHROPIC_API_KEY or GOOGLE_GENAI_API_KEY for "
            "real reasoning]"
        )

    async def generate_structured(
        self, prompt: str, schema: type[T], system: Optional[str] = None
    ) -> Optional[T]:
        return None


class AnthropicProvider:
    """Claude backend via the official ``anthropic`` SDK (lazy import)."""

    name = "anthropic"

    def __init__(
        self,
        api_key: str = ANTHROPIC_API_KEY,
        model: str = ANTHROPIC_MODEL,
        effort: str = ANTHROPIC_EFFORT,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._effort = effort
        self._client: Any = None
        self._sdk_ok: Optional[bool] = None

    def _get_client(self) -> Any:
        if self._client is None and self._api_key:
            try:
                from anthropic import AsyncAnthropic

                self._client = AsyncAnthropic(api_key=self._api_key)
                self._sdk_ok = True
            except Exception as exc:  # pragma: no cover - import/runtime guard
                logger.warning("Anthropic SDK unavailable: %s", exc)
                self._sdk_ok = False
        return self._client

    def available(self) -> bool:
        if not self._api_key:
            return False
        return self._get_client() is not None

    async def generate(self, prompt: str, system: Optional[str] = None) -> str:
        client = self._get_client()
        if client is None:
            return ""
        try:
            resp = await client.messages.create(
                model=self._model,
                max_tokens=4096,
                system=system or "You are an expert flood-risk reasoning assistant.",
                thinking={"type": "adaptive"},
                output_config={"effort": self._effort},
                messages=[{"role": "user", "content": prompt}],
            )
            return "".join(
                b.text for b in resp.content if getattr(b, "type", None) == "text"
            )
        except Exception as exc:
            logger.warning("AnthropicProvider.generate failed: %s", exc)
            return f"[LLM error: {exc}]"

    async def generate_structured(
        self, prompt: str, schema: type[T], system: Optional[str] = None
    ) -> Optional[T]:
        client = self._get_client()
        if client is None:
            return None
        sys_prompt = system or "You are an expert flood-risk reasoning assistant."
        # Preferred path: SDK-native structured output (messages.parse).
        try:
            parse = getattr(client.messages, "parse", None)
            if parse is not None:
                resp = await parse(
                    model=self._model,
                    max_tokens=4096,
                    system=sys_prompt,
                    thinking={"type": "adaptive"},
                    output_config={"effort": self._effort},
                    messages=[{"role": "user", "content": prompt}],
                    output_format=schema,
                )
                parsed = getattr(resp, "parsed_output", None)
                if isinstance(parsed, schema):
                    return parsed
        except Exception as exc:
            logger.info("messages.parse unavailable/failed, falling back: %s", exc)
        # Fallback: ask for JSON and validate against the schema.
        try:
            instructions = (
                f"{sys_prompt}\n\nRespond with ONLY a JSON object matching this schema:\n"
                f"{json.dumps(schema.model_json_schema())}"
            )
            text = await self.generate(prompt, system=instructions)
            data = _extract_json(text)
            if data is not None:
                return schema.model_validate(data)
        except Exception as exc:
            logger.warning("AnthropicProvider structured fallback failed: %s", exc)
        return None


class GeminiProvider:
    """Google Gemini backend via the ``google-genai`` SDK (lazy import)."""

    name = "gemini"

    def __init__(
        self, api_key: str = GOOGLE_GENAI_API_KEY, model: str = GEMINI_MODEL
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._client: Any = None

    def _get_client(self) -> Any:
        if self._client is None and self._api_key:
            try:
                from google import genai

                self._client = genai.Client(api_key=self._api_key)
            except Exception as exc:  # pragma: no cover - import/runtime guard
                logger.warning("Gemini SDK unavailable: %s", exc)
                self._client = None
        return self._client

    def available(self) -> bool:
        if not self._api_key:
            return False
        return self._get_client() is not None

    async def generate(self, prompt: str, system: Optional[str] = None) -> str:
        client = self._get_client()
        if client is None:
            return ""
        try:
            config: dict[str, Any] = {}
            if system:
                config["system_instruction"] = system
            resp = client.models.generate_content(
                model=self._model,
                contents=prompt,
                config=config or None,
            )
            return resp.text or ""
        except Exception as exc:
            logger.warning("GeminiProvider.generate failed: %s", exc)
            return f"[LLM error: {exc}]"

    async def generate_structured(
        self, prompt: str, schema: type[T], system: Optional[str] = None
    ) -> Optional[T]:
        client = self._get_client()
        if client is None:
            return None
        try:
            config: dict[str, Any] = {
                "response_mime_type": "application/json",
                "response_schema": schema,
            }
            if system:
                config["system_instruction"] = system
            resp = client.models.generate_content(
                model=self._model, contents=prompt, config=config
            )
            parsed = getattr(resp, "parsed", None)
            if isinstance(parsed, schema):
                return parsed
            data = _extract_json(resp.text or "")
            if data is not None:
                return schema.model_validate(data)
        except Exception as exc:
            logger.warning("GeminiProvider structured failed: %s", exc)
        return None


def make_provider(which: str = FLOODOPS_LLM_PROVIDER) -> LLMProvider:
    """Build a provider from config/env.

    ``which`` is one of ``anthropic`` | ``gemini`` | ``auto``. ``auto`` returns
    the first provider whose key is set, else a ``NullProvider``.
    """
    which = (which or "auto").lower()
    if which == "anthropic":
        return AnthropicProvider()
    if which == "gemini":
        return GeminiProvider()

    # auto — prefer Anthropic, then Gemini, else null.
    anthropic = AnthropicProvider()
    if anthropic.available():
        return anthropic
    gemini = GeminiProvider()
    if gemini.available():
        return gemini
    logger.info("No LLM key configured — using NullProvider (mock fallbacks active)")
    return NullProvider()
