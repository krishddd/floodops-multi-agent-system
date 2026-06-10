"""
AgentMemory — bounded, in-memory vector store for historical-event recall.

DEV-ONLY / NOT RESTART-SAFE: events live in process memory and are lost on
restart (durable persistence is out of scope for v2). Growth is bounded by
``MEMORY_MAX_EVENTS`` with FIFO eviction.

Embedding strategy (explicit, never faked):
  (a) a provided ``embed_fn`` (e.g. an LLM-provider embedder) when available;
  (b) else ``sentence-transformers`` all-MiniLM-L6-v2 for genuine semantic
      recall with NO API key (optional dep — see requirements-ml.txt);
  (c) if neither is present, recall is DISABLED and ``recall_similar`` returns
      ``[]``. We do not use a hashing pseudo-embedder (semantically meaningless).
"""

from __future__ import annotations

import math
import uuid
from collections import deque
from collections.abc import Callable

from floodops.config import MEMORY_MAX_EVENTS
from floodops.models.memory import MemoryRecord, RecalledEvent


def _load_sentence_transformer():  # pragma: no cover - optional heavy dep
    try:
        from sentence_transformers import SentenceTransformer  # type: ignore[import-not-found]

        return SentenceTransformer("all-MiniLM-L6-v2")
    except Exception:
        return None


class AgentMemory:
    """Bounded FIFO vector store with cosine recall."""

    def __init__(
        self,
        max_events: int = MEMORY_MAX_EVENTS,
        embed_fn: Callable[[str], list[float]] | None = None,
    ) -> None:
        self._store: deque[MemoryRecord] = deque(maxlen=max_events)
        self._embed_fn = embed_fn
        self._model = None
        self._model_tried = False

    def _embed(self, text: str) -> list[float] | None:
        if self._embed_fn is not None:  # (a) injected embedder
            try:
                return list(self._embed_fn(text))
            except Exception:
                return None
        if not self._model_tried:  # (b) sentence-transformers, lazy + once
            self._model_tried = True
            self._model = _load_sentence_transformer()
        if self._model is not None:  # pragma: no cover - requires heavy dep
            return list(self._model.encode(text))
        return None  # (c) disabled

    @property
    def enabled(self) -> bool:
        """True when an embedder is available (recall is meaningful)."""
        if self._embed_fn is not None:
            return True
        if not self._model_tried:
            self._model_tried = True
            self._model = _load_sentence_transformer()
        return self._model is not None

    def remember(self, agent_id: str, summary: str, metadata: dict | None = None) -> None:
        vec = self._embed(summary)
        if vec is None:
            return  # recall disabled — don't store unembeddable records
        self._store.append(MemoryRecord(
            record_id=str(uuid.uuid4()), agent_id=agent_id, summary=summary,
            vector=vec, metadata=metadata or {},
        ))

    def recall_similar(self, query: str, k: int = 3) -> list[RecalledEvent]:
        qvec = self._embed(query)
        if qvec is None or not self._store:
            return []
        scored = [
            (self._cosine(qvec, r.vector), r) for r in self._store if r.vector
        ]
        scored.sort(key=lambda t: t[0], reverse=True)
        return [
            RecalledEvent(summary=r.summary, similarity=round(s, 3),
                          created_at=r.created_at, metadata=r.metadata)
            for s, r in scored[:k]
        ]

    @staticmethod
    def _cosine(a: list[float], b: list[float]) -> float:
        if not a or not b or len(a) != len(b):
            return 0.0
        dot = sum(x * y for x, y in zip(a, b, strict=False))
        na = math.sqrt(sum(x * x for x in a))
        nb = math.sqrt(sum(y * y for y in b))
        return dot / (na * nb) if na and nb else 0.0
