"""
🟢 LIVE — USGS Water Services Connector.

Source: api.waterdata.usgs.gov (National Water Information System)
Python library: dataretrieval-python

Data cadence: 🟢 15 minutes (real-time river gauges)
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Optional

from floodops.connectors.base import BaseConnector
from floodops.models.enums import DataSource
from floodops.models.geo import BBox


class USGSConnector(BaseConnector):
    """USGS real-time river gauge data connector.

    Uses the NWIS Instantaneous Values (IV) service for 15-min gauge readings.
    Parameters tracked:
    - 00060: Discharge (cfs)
    - 00065: Gage height (ft)
    - 72192: Reservoir storage (acre-ft)
    """

    source = DataSource.USGS_GAUGES
    expected_cadence = "15 min"
    is_mock = False

    USGS_BASE = "https://waterservices.usgs.gov/nwis/iv/"

    async def health_check(self) -> bool:
        try:
            data = await self.fetch_with_retry(
                self.USGS_BASE,
                params={"format": "json", "sites": "01646500", "parameterCd": "00065", "period": "PT1H"},
            )
            return bool(data)
        except Exception:
            return False

    async def fetch_latest(self, site_ids: Optional[list[str]] = None, bbox: Optional[BBox] = None, **kwargs: Any) -> dict:
        """Fetch latest gauge readings for specified sites or bounding box."""
        params: dict[str, str] = {
            "format": "json",
            "parameterCd": "00065,00060",  # Gage height + discharge
            "siteStatus": "active",
            "period": "PT2H",  # Last 2 hours of data
        }

        if site_ids:
            params["sites"] = ",".join(site_ids)
        elif bbox:
            params["bBox"] = f"{bbox.west},{bbox.south},{bbox.east},{bbox.north}"
        else:
            # Default: Kathmandu region (no USGS gauges — fall back to sample)
            params["sites"] = "01646500"  # Potomac River as demo

        try:
            data = await self.fetch_with_retry(self.USGS_BASE, params=params)
            return self._parse_response(data)
        except Exception:
            return {"sites": [], "error": "USGS API unreachable"}

    def _parse_response(self, raw: dict) -> dict:
        """Parse USGS IV JSON response into normalized sensor readings."""
        time_series = raw.get("value", {}).get("timeSeries", [])
        sites = []

        for ts in time_series:
            site_info = ts.get("sourceInfo", {})
            variable = ts.get("variable", {})
            values = ts.get("values", [{}])[0].get("value", [])

            if not values:
                continue

            latest = values[-1]
            geo = site_info.get("geoLocation", {}).get("geogLocation", {})

            sites.append({
                "site_id": site_info.get("siteCode", [{}])[0].get("value", ""),
                "site_name": site_info.get("siteName", ""),
                "lat": geo.get("latitude", 0),
                "lng": geo.get("longitude", 0),
                "parameter": variable.get("variableCode", [{}])[0].get("value", ""),
                "parameter_name": variable.get("variableName", ""),
                "value": float(latest.get("value", 0)),
                "unit": variable.get("unit", {}).get("unitAbbreviation", ""),
                "datetime": latest.get("dateTime", ""),
                "qualifier": latest.get("qualifiers", []),
            })

        return {"sites": sites, "count": len(sites)}

    async def get_site_info(self, site_id: str) -> dict:
        """Fetch metadata for a specific gauge site."""
        params = {"format": "json", "sites": site_id, "siteOutput": "expanded"}
        return await self.fetch_with_retry("https://waterservices.usgs.gov/nwis/site/", params=params)
