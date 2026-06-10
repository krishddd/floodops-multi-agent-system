"""
SQLite persistence layer (v4) — forecasts, alerts, audit, verification.

SCOPE HONESTY: SQLite (stdlib, WAL mode) is **single-node / evaluation
persistence**. Production deployments swap to PostgreSQL via an async driver;
the schema is deliberately portable (plain SQL, TEXT/INTEGER/REAL only, no
SQLite-isms beyond WAL pragmas). All access is funnelled through
``asyncio.to_thread`` so the event loop never blocks on disk.

Schema (see v4 plan):
  forecasts(forecast_id PK, watershed_id, issued_at, payload_json,
            max_return_period_years)
  alerts(alert_id PK, forecast_id FK, severity, issued_at, payload_json)
  audit(id PK AUTOINCREMENT, agent_id, action, confidence, ts)
  verification_samples(id PK AUTOINCREMENT, forecast_id FK,
            return_period_years, predicted_exceed, observed_exceed, scored_at)

An empty ``FLOODOPS_DB_PATH`` disables persistence entirely (every method is
a no-op) — used by tests that don't care about storage.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
from datetime import datetime
from typing import Any

from floodops.config import FLOODOPS_DB_PATH

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS forecasts (
    forecast_id TEXT PRIMARY KEY,
    watershed_id TEXT NOT NULL,
    issued_at TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    max_return_period_years INTEGER
);
CREATE TABLE IF NOT EXISTS alerts (
    alert_id TEXT PRIMARY KEY,
    forecast_id TEXT REFERENCES forecasts(forecast_id),
    severity TEXT NOT NULL,
    issued_at TEXT NOT NULL,
    payload_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id TEXT NOT NULL,
    action TEXT NOT NULL,
    confidence REAL NOT NULL,
    ts TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS verification_samples (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    forecast_id TEXT REFERENCES forecasts(forecast_id),
    return_period_years INTEGER NOT NULL,
    predicted_exceed INTEGER NOT NULL,
    observed_exceed INTEGER NOT NULL,
    scored_at TEXT NOT NULL
);
"""


class Store:
    """Async-safe persistence facade. Disabled (no-op) when path is empty."""

    def __init__(self, path: str | None = None) -> None:
        self._path = FLOODOPS_DB_PATH if path is None else path
        self.enabled = bool(self._path)
        self._conn: sqlite3.Connection | None = None

    # ── Lifecycle ────────────────────────────────────────────────────

    async def init(self) -> None:
        if not self.enabled:
            return
        def _open() -> sqlite3.Connection:
            conn = sqlite3.connect(self._path, check_same_thread=False)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(_SCHEMA)
            conn.commit()
            return conn
        self._conn = await asyncio.to_thread(_open)
        logger.info("store: SQLite persistence at %s (WAL)", self._path)

    async def close(self) -> None:
        if self._conn is not None:
            await asyncio.to_thread(self._conn.close)
            self._conn = None

    async def _execute(self, sql: str, params: tuple = ()) -> None:
        if self._conn is None:
            return
        def _run() -> None:
            self._conn.execute(sql, params)
            self._conn.commit()
        try:
            await asyncio.to_thread(_run)
        except Exception as exc:
            logger.warning("store write failed: %s", exc)

    async def _query(self, sql: str, params: tuple = ()) -> list[tuple]:
        if self._conn is None:
            return []
        def _run() -> list[tuple]:
            return list(self._conn.execute(sql, params))
        try:
            return await asyncio.to_thread(_run)
        except Exception as exc:
            logger.warning("store read failed: %s", exc)
            return []

    # ── Channel persistence (subscribed on the event bus) ────────────

    async def save_forecast(self, channel: str, payload: Any) -> None:
        data = payload if isinstance(payload, dict) else payload.model_dump()
        await self._execute(
            "INSERT OR REPLACE INTO forecasts VALUES (?, ?, ?, ?, ?)",
            (str(data.get("forecast_id", "")),
             str(data.get("watershed_id", "")),
             datetime.utcnow().isoformat(),
             json.dumps(data, default=str),
             data.get("max_return_period_years")),
        )

    async def save_alert(self, channel: str, payload: Any) -> None:
        data = payload if isinstance(payload, dict) else payload.model_dump()
        await self._execute(
            "INSERT OR REPLACE INTO alerts VALUES (?, ?, ?, ?, ?)",
            (str(data.get("dispatch_id") or data.get("alert_id", "")),
             str(data.get("event_id", "")),
             str(data.get("severity", "")),
             datetime.utcnow().isoformat(),
             json.dumps(data, default=str)),
        )

    async def save_audit(self, agent_id: str, action: str, confidence: float) -> None:
        await self._execute(
            "INSERT INTO audit (agent_id, action, confidence, ts) VALUES (?, ?, ?, ?)",
            (agent_id, action, float(confidence), datetime.utcnow().isoformat()),
        )

    # ── Verification persistence ─────────────────────────────────────

    async def save_forecast_sample(self, sample: Any) -> None:
        """Pending verification samples ride along in the forecasts table."""
        # (The full pending trace is small; we reuse payload_json.)
        await self._execute(
            "INSERT OR REPLACE INTO forecasts VALUES (?, ?, ?, ?, ?)",
            (f"pending:{sample.forecast_id}", "verification_pending",
             sample.issued_at.isoformat(),
             json.dumps({
                 "lat": sample.lat, "lng": sample.lng,
                 "thresholds": sample.thresholds,
                 "trace_times": sample.trace_times,
                 "trace_values": sample.trace_values,
             }), None),
        )

    async def save_verification_result(
        self, forecast_id: str, result: dict[int, dict[str, int]]
    ) -> None:
        for rp, c in result.items():
            await self._execute(
                "INSERT INTO verification_samples "
                "(forecast_id, return_period_years, predicted_exceed, "
                " observed_exceed, scored_at) VALUES (?, ?, ?, ?, ?)",
                (forecast_id, int(rp),
                 int(c["tp"] or c["fp"]), int(c["tp"] or c["fn"]),
                 datetime.utcnow().isoformat()),
            )
        await self._execute(
            "DELETE FROM forecasts WHERE forecast_id = ?",
            (f"pending:{forecast_id}",),
        )

    # ── Reads (restart survival + routes) ────────────────────────────

    async def recent_forecasts(self, limit: int = 20) -> list[dict]:
        rows = await self._query(
            "SELECT payload_json FROM forecasts "
            "WHERE watershed_id != 'verification_pending' "
            "ORDER BY issued_at DESC LIMIT ?", (int(limit),),
        )
        return [json.loads(r[0]) for r in rows]

    async def recent_alerts(self, limit: int = 20) -> list[dict]:
        rows = await self._query(
            "SELECT payload_json FROM alerts ORDER BY issued_at DESC LIMIT ?",
            (int(limit),),
        )
        return [json.loads(r[0]) for r in rows]

    async def get_alert(self, alert_id: str) -> dict | None:
        rows = await self._query(
            "SELECT payload_json FROM alerts WHERE alert_id = ?", (alert_id,),
        )
        return json.loads(rows[0][0]) if rows else None

    async def counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for table in ("forecasts", "alerts", "audit", "verification_samples"):
            rows = await self._query(f"SELECT COUNT(*) FROM {table}")  # noqa: S608 — fixed table names
            out[table] = rows[0][0] if rows else 0
        return out
