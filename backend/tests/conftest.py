"""
Shared pytest fixtures for FloodOps.

Provides a deterministic ``FakeProvider`` so the reasoning-core helpers can be
exercised WITH an "LLM" present, fully offline (no network, no API key). Also
provides a no-key ``FloodLLMClient`` to prove every agent degrades gracefully.
"""

from __future__ import annotations

import pytest

from floodops.llm.client import FloodLLMClient
from floodops.queue.event_bus import EventBus


class FakeProvider:
    """Deterministic offline LLM provider for tests.

    ``confidence_seq`` lets a test script a low-then-high confidence sequence to
    exercise the Reflexion retry loop. Each ``generate_structured`` call returns
    the configured schema populated with the next confidence value.
    """

    name = "fake"

    def __init__(self, confidence_seq: list[float] | None = None,
                 value: float = 0.8, summary: str = "fake-reasoning"):
        self._confidence_seq = list(confidence_seq or [0.9])
        self._value = value
        self._summary = summary
        self.calls = 0

    def available(self) -> bool:
        return True

    async def generate(self, prompt: str, system: str | None = None) -> str:
        return f"critique-{self.calls}"

    async def generate_structured(self, prompt, schema, system=None):
        self.calls += 1
        conf = self._confidence_seq[min(self.calls - 1, len(self._confidence_seq) - 1)]
        fields = {"summary": self._summary, "value": self._value, "confidence": conf}
        # Populate only the fields the schema actually declares.
        data = {k: v for k, v in fields.items() if k in schema.model_fields}
        return schema(**data)


@pytest.fixture
def fake_llm():
    """A FloodLLMClient backed by a default FakeProvider (high confidence)."""
    return FloodLLMClient(provider=FakeProvider())


@pytest.fixture
def reflexion_llm():
    """A FloodLLMClient whose first attempt is low-confidence, then high."""
    return FloodLLMClient(provider=FakeProvider(confidence_seq=[0.3, 0.9]))


@pytest.fixture
def nokey_llm():
    """A FloodLLMClient with no provider configured (NullProvider)."""
    from floodops.llm.providers import NullProvider

    return FloodLLMClient(provider=NullProvider())


@pytest.fixture
def event_bus():
    return EventBus()
