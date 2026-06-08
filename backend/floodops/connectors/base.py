"""
BaseConnector — Abstract base for all data source connectors.

Provides: rate limiting, exponential backoff, in-memory caching,
health checking, and honest data-cadence reporting.

Every connector (live or mock) inherits this. Mock connectors return
the EXACT same data schema as live — swapping is a config change.
"""

from __future__ import annotations

import asyncio
import hashlib
import time
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Optional

import httpx

from floodops.models.enums import ConnectorStatus, DataSource
from floodops.models.geo import DataCadenceBadge


class BaseConnector(ABC):
    """Abstract base for all data source connectors."""

    source: DataSource
    expected_cadence: str = "unknown"
    is_mock: bool = False

    def __init__(
        self,
        rate_limit_per_second: float = 2.0,
        max_retries: int = 3,
        cache_ttl_seconds: int = 300,
        timeout_seconds: float = 30.0,
    ):
        self._rate_limit = rate_limit_per_second
        self._max_retries = max_retries
        self._cache_ttl = cache_ttl_seconds
        self._timeout = timeout_seconds
        self._cache: dict[str, tuple[float, Any]] = {}
        self._last_request_time: float = 0.0
        self._last_data_time: Optional[str] = None
        self._status: ConnectorStatus = ConnectorStatus.MOCK if self.is_mock else ConnectorStatus.LIVE
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=self._timeout)
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def _rate_limit_wait(self) -> None:
        """Enforce rate limit between requests."""
        now = time.monotonic()
        elapsed = now - self._last_request_time
        min_interval = 1.0 / self._rate_limit
        if elapsed < min_interval:
            await asyncio.sleep(min_interval - elapsed)
        self._last_request_time = time.monotonic()

    def _cache_key(self, *args: Any) -> str:
        raw = str(args).encode()
        return hashlib.md5(raw).hexdigest()

    def _get_cached(self, key: str) -> Optional[Any]:
        if key in self._cache:
            ts, data = self._cache[key]
            if time.time() - ts < self._cache_ttl:
                return data
            del self._cache[key]
        return None

    def _set_cached(self, key: str, data: Any) -> None:
        self._cache[key] = (time.time(), data)

    async def fetch_with_retry(self, url: str, params: Optional[dict] = None, headers: Optional[dict] = None) -> dict:
        """Fetch URL with rate limiting, retries, and exponential backoff."""
        cache_key = self._cache_key(url, params)
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        client = await self._get_client()
        last_error = None

        for attempt in range(self._max_retries):
            await self._rate_limit_wait()
            try:
                resp = await client.get(url, params=params, headers=headers)
                resp.raise_for_status()
                data = resp.json()
                self._set_cached(cache_key, data)
                self._last_data_time = datetime.utcnow().isoformat()
                self._status = ConnectorStatus.LIVE
                return data
            except Exception as e:
                last_error = e
                wait = (2 ** attempt) * 0.5
                await asyncio.sleep(wait)

        self._status = ConnectorStatus.ERROR
        raise ConnectionError(f"Failed after {self._max_retries} retries: {last_error}")

    def get_cadence_badge(self) -> DataCadenceBadge:
        """Generate honest data-cadence badge for UI."""
        if self.is_mock:
            emoji = "⚪"
            freshness = "static"
        elif self._status == ConnectorStatus.ERROR:
            emoji = "🔴"
            freshness = "stale"
        elif self._last_data_time:
            emoji = "🟢"
            freshness = "fresh"
        else:
            emoji = "🟡"
            freshness = "within_cadence"

        return DataCadenceBadge(
            source=self.source.value if hasattr(self.source, "value") else str(self.source),
            expected_cadence=self.expected_cadence,
            last_updated_iso=self._last_data_time,
            freshness=freshness,
            emoji=emoji,
        )

    @abstractmethod
    async def health_check(self) -> bool:
        """Check if the connector can reach its data source."""

    @abstractmethod
    async def fetch_latest(self, **kwargs: Any) -> Any:
        """Fetch the latest data from the source."""
