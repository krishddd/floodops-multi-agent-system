"""Tests for B3: agent memory (bounded FIFO + cosine recall) and causal graph."""

from __future__ import annotations

from floodops.llm.memory import AgentMemory
from floodops.models.causal import CausalGraph


def _toy_embed(text: str) -> list[float]:
    """Deterministic 3-dim bag-of-keywords embedder for tests (not production)."""
    t = text.lower()
    return [
        float(t.count("flood")),
        float(t.count("glof") + t.count("dam")),
        float(t.count("disease") + t.count("cholera")),
    ]


def test_recall_disabled_without_embedder():
    # No embed_fn and (assume) no sentence-transformers installed → recall off.
    mem = AgentMemory(embed_fn=None)
    if not mem.enabled:  # if the heavy model isn't present in this env
        mem.remember("predict", "Flood in Bagmati 90%")
        assert mem.recall_similar("flood") == []


def test_recall_returns_semantic_nearest_with_embedder():
    mem = AgentMemory(embed_fn=_toy_embed)
    assert mem.enabled
    mem.remember("predict", "Major flood in Bagmati corridor, 90% probability")
    mem.remember("glof", "Dam integrity low, GLOF breach imminent")
    mem.remember("disease", "Cholera outbreak risk after flood recedes")

    hits = mem.recall_similar("flood inundation forecast", k=2)
    assert hits, "expected recall results"
    assert "flood" in hits[0].summary.lower()
    assert 0.0 <= hits[0].similarity <= 1.0


def test_memory_is_bounded_fifo():
    mem = AgentMemory(max_events=3, embed_fn=_toy_embed)
    for i in range(5):
        mem.remember("predict", f"flood event {i}")
    # Only the last 3 are retained (FIFO eviction).
    hits = mem.recall_similar("flood", k=10)
    summaries = {h.summary for h in hits}
    assert len(hits) == 3
    assert "flood event 0" not in summaries and "flood event 1" not in summaries
    assert "flood event 4" in summaries


def test_causal_graph_from_config_ranks_upstream():
    g = CausalGraph.from_config("bagmati")
    assert g.region == "bagmati"
    assert len(g.edges) >= 4
    factors = g.ranked_causal_factors()
    assert factors, "expected ranked causal factors from the basin outlet"
    assert any("upstream inflow" in f for f in factors)


def test_causal_graph_unknown_region_is_empty():
    g = CausalGraph.from_config("nonexistent")
    assert g.edges == []
    assert g.ranked_causal_factors() == []
