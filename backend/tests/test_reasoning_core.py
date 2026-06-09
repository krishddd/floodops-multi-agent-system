"""Tests for the shared core-3 reasoning helpers on BaseAgent."""

from __future__ import annotations

import pytest

from floodops.agents.base import BaseAgent, _as_dict
from floodops.models.enums import TriggerType
from floodops.models.reasoning import ReasonedAssessment, UncertaintyBounds


class _DummyAgent(BaseAgent):
    agent_id = "dummy"
    trigger_types = {TriggerType.QUEUE}

    async def initialize(self) -> None:  # pragma: no cover - not used
        pass

    async def handle_event(self, channel, payload) -> None:  # pragma: no cover
        pass


def _mock() -> ReasonedAssessment:
    return ReasonedAssessment(value=0.5, confidence=0.5, summary="mock")


@pytest.mark.asyncio
async def test_reflexion_retries_until_confident(reflexion_llm, event_bus):
    """First attempt is low-confidence → loop critiques and retries → high."""
    agent = _DummyAgent(event_bus, llm=reflexion_llm)
    result = await agent._run_with_reflexion(
        "sys", {"x": 1}, None, ReasonedAssessment, _mock(), floor=0.75, max_retries=3
    )
    assert result.confidence >= 0.75
    # Two structured calls (0.3 then 0.9) — proves the retry happened.
    assert reflexion_llm._provider.calls == 2


@pytest.mark.asyncio
async def test_ensemble_vote_returns_consensus(fake_llm, event_bus):
    agent = _DummyAgent(event_bus, llm=fake_llm)
    result = await agent._ensemble_vote(
        "sys", {"x": 1}, None, ReasonedAssessment, _mock(), runs=3
    )
    assert isinstance(result, ReasonedAssessment)
    assert result.value == pytest.approx(0.8)
    assert fake_llm._provider.calls == 3  # 3-run consensus


@pytest.mark.asyncio
async def test_helpers_fall_back_to_mock_without_key(nokey_llm, event_bus):
    """With no LLM, every helper returns the caller-supplied mock unchanged."""
    agent = _DummyAgent(event_bus, llm=nokey_llm)
    mock = _mock()
    assert (await agent._run_with_reflexion("s", {}, None, ReasonedAssessment, mock)) is mock
    assert (await agent._ensemble_vote("s", {}, None, ReasonedAssessment, mock)) is mock


@pytest.mark.asyncio
async def test_helpers_fall_back_when_llm_is_none(event_bus):
    agent = _DummyAgent(event_bus, llm=None)
    mock = _mock()
    assert (await agent._run_with_reflexion("s", {}, None, ReasonedAssessment, mock)) is mock


def test_quantify_uncertainty_bounds(event_bus):
    agent = _DummyAgent(event_bus)
    bounds = agent._quantify_uncertainty([0.2, 0.5, 0.8, 0.9, 0.3])
    assert isinstance(bounds, UncertaintyBounds)
    assert bounds.low <= bounds.point <= bounds.high
    assert 0.1 <= bounds.confidence <= 1.0


def test_quantify_uncertainty_empty_is_safe(event_bus):
    agent = _DummyAgent(event_bus)
    bounds = agent._quantify_uncertainty([])
    assert bounds.confidence == 0.1


def test_reasoned_assessment_rejects_tiny_confidence():
    with pytest.raises(ValueError):
        ReasonedAssessment(value=0.5, confidence=0.05, summary="bad")


def test_as_dict_coerces_pydantic_and_dict():
    m = _mock()
    assert _as_dict(m)["value"] == 0.5
    assert _as_dict({"a": 1}) == {"a": 1}
    assert _as_dict(None) == {}
