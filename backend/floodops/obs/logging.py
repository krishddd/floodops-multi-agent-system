"""
Structured JSON logging for FloodOps.

One log line == one JSON object, so logs are greppable/ingestable. A correlation
id (the active flood ``event_id``) is attached when available via a context var,
so an operator can trace a single flood event across all 8 agents.
"""

from __future__ import annotations

import contextvars
import json
import logging
from datetime import datetime
from typing import Any

# Correlation id for the active event — set by the orchestrator / agents.
correlation_id: contextvars.ContextVar[str] = contextvars.ContextVar(
    "correlation_id", default=""
)

_RESERVED = {
    "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
    "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
    "created", "msecs", "relativeCreated", "thread", "threadName",
    "processName", "process", "taskName",
}


class JsonFormatter(logging.Formatter):
    """Render each record as a single JSON object."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.utcfromtimestamp(record.created).isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        cid = correlation_id.get()
        if cid:
            payload["event_id"] = cid
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        # Include any extra={...} fields.
        for k, v in record.__dict__.items():
            if k not in _RESERVED and k not in payload and not k.startswith("_"):
                payload[k] = v
        return json.dumps(payload, default=str)


def setup_logging(level: str = "INFO") -> None:
    """Install the JSON formatter on the root logger (idempotent)."""
    root = logging.getLogger()
    root.setLevel(level)
    # Replace existing handlers' formatter rather than stacking handlers.
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root.handlers = [handler]


def set_correlation_id(event_id: str) -> None:
    correlation_id.set(event_id or "")
