"""
🟡 LIVE (free registration) — ReliefWeb humanitarian reports connector.

Source: UN OCHA ReliefWeb API v2 (``https://api.reliefweb.int/v2``).
The API requires an **approved appname** (free, registered at
https://apidoc.reliefweb.int/parameters#appname) passed via the
``RELIEFWEB_APPNAME`` env var. Without one the API returns 403 and this
connector degrades honestly: ``health_check()`` is False and consumers
proceed without humanitarian context (never faked).

IMPORTANT — LATENCY: humanitarian reports typically lag events by 2–7 days.
Every payload carries ``report_lag_days`` and consumers must treat this as
*retrospective context* (post-flood disease risk, sitrep background), NEVER a
real-time hazard signal. The DiseaseRiskAgent prompt labels it accordingly.

Cache TTL 6h (reports are slow-moving). Degrades to None/[] on failure.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any

from floodops.connectors.base import BaseConnector
from floodops.models.enums import DataSource

_APPNAME = os.getenv("RELIEFWEB_APPNAME", "floodops-demo")


class ReliefWebConnector(BaseConnector):
    """Keyless humanitarian situation context (retrospective, days-old)."""

    source = DataSource.RELIEFWEB
    expected_cadence = "daily"
    is_mock = False

    REPORTS_BASE = "https://api.reliefweb.int/v2/reports"

    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("cache_ttl_seconds", 21600)  # 6h
        super().__init__(**kwargs)

    async def health_check(self) -> bool:
        try:
            await self.fetch_with_retry(
                self.REPORTS_BASE, params={"appname": _APPNAME, "limit": 1}
            )
            return True
        except Exception:
            return False

    async def fetch_latest(self, **kwargs: Any) -> dict:
        reports = await self.get_flood_reports(kwargs.get("query", "flood")) or []
        return {"reports": reports}

    async def get_flood_reports(
        self, query: str = "flood", limit: int = 5
    ) -> list[dict] | None:
        """Latest flood-related reports with explicit ``report_lag_days``.

        Each report: ``{title, url, date, report_lag_days, source}``. Returns
        None on failure (never faked).
        """
        try:
            data = await self.fetch_with_retry(
                self.REPORTS_BASE,
                params={
                    "appname": _APPNAME,
                    "query[value]": query,
                    "query[fields][]": "title",
                    "fields[include][]": "date.created",
                    "limit": limit,
                    "sort[]": "date.created:desc",
                },
            )
            now = datetime.now(UTC)
            reports: list[dict] = []
            for item in data.get("data", []):
                fields = item.get("fields", {})
                created = (fields.get("date") or {}).get("created")
                lag_days: float | None = None
                if created:
                    try:
                        dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
                        lag_days = round((now - dt).total_seconds() / 86400, 1)
                    except ValueError:
                        pass
                reports.append({
                    "title": fields.get("title") or item.get("href", ""),
                    "url": item.get("href"),
                    "date": created,
                    "report_lag_days": lag_days,
                    "context_note": (
                        "retrospective humanitarian context (days-old), "
                        "NOT a real-time signal"
                    ),
                })
            return reports
        except Exception:
            return None
