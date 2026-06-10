"""
Common Alerting Protocol 1.2 rendering (v4) — the standard agencies consume.

CAP 1.2 (OASIS) is the dissemination format used by national alerting
authorities and by the operational system behind Nearing et al. 2024 (Google
Flood Hub publishes via CAP). This module renders an AlertAgent dispatch as a
CAP ``<alert>`` document.

INJECTION SAFETY (pinned in the v4 plan): the document is built exclusively
with ``xml.etree.ElementTree`` — text content is escaped by the serializer,
never string-templated. External-origin strings (event names from GDACS,
basin ids) are additionally length-capped before insertion. The deterministic
severity mapping is the AlertAgent's (LLM never gates it).
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import datetime
from typing import Any

CAP_NS = "urn:oasis:names:tc:emergency:cap:1.2"

#: FloodOps SeverityLevel → CAP severity / urgency / certainty.
_SEVERITY_MAP: dict[str, tuple[str, str, str]] = {
    "ADVISORY": ("Minor", "Future", "Possible"),
    "WATCH": ("Moderate", "Expected", "Likely"),
    "WARNING": ("Severe", "Expected", "Likely"),
    "EMERGENCY": ("Extreme", "Immediate", "Observed"),
}

_MAX_FIELD_LEN = 512  # cap external-origin strings


def _capped(value: Any, limit: int = _MAX_FIELD_LEN) -> str:
    return str(value)[:limit]


def to_cap_xml(dispatch: dict[str, Any], sender: str = "floodops@demo") -> str:
    """Render an AlertDispatch dict as a CAP 1.2 XML string.

    Returns a complete, well-formed ``<alert>`` document. Any missing fields
    fall back to safe defaults — the function never raises on dirty input.
    """
    severity_key = str(dispatch.get("severity", "ADVISORY")).upper()
    cap_severity, urgency, certainty = _SEVERITY_MAP.get(
        severity_key, ("Unknown", "Unknown", "Unknown")
    )

    ET.register_namespace("", CAP_NS)
    alert = ET.Element(f"{{{CAP_NS}}}alert")

    def _add(parent: ET.Element, tag: str, text: str) -> ET.Element:
        el = ET.SubElement(parent, f"{{{CAP_NS}}}{tag}")
        el.text = text  # ElementTree escapes on serialization
        return el

    _add(alert, "identifier", _capped(dispatch.get("dispatch_id")
                                      or dispatch.get("alert_id") or "unknown"))
    _add(alert, "sender", _capped(sender, 128))
    sent = dispatch.get("timestamp") or datetime.utcnow().isoformat()
    # CAP requires a timezone-qualified datetime.
    sent_str = str(sent)[:19] + ("+00:00" if "T" in str(sent) else "")
    _add(alert, "sent", sent_str or datetime.utcnow().isoformat() + "+00:00")
    _add(alert, "status", "Actual" if severity_key in ("WARNING", "EMERGENCY")
         else "Exercise")
    _add(alert, "msgType", "Alert")
    _add(alert, "scope", "Public")

    info = ET.SubElement(alert, f"{{{CAP_NS}}}info")
    _add(info, "language", "en-US")
    _add(info, "category", "Met")
    _add(info, "event", _capped(f"Flood {severity_key.title()}", 128))
    _add(info, "responseType", "Evacuate" if severity_key == "EMERGENCY"
         else "Prepare" if severity_key == "WARNING" else "Monitor")
    _add(info, "urgency", urgency)
    _add(info, "severity", cap_severity)
    _add(info, "certainty", certainty)
    _add(info, "senderName", "FloodOps Multi-Agent Flood Management System")

    # Headline/description from the first cell broadcast if present.
    broadcasts = dispatch.get("cell_broadcasts") or []
    message = (broadcasts[0].get("message_text", "")
               if broadcasts and isinstance(broadcasts[0], dict) else "")
    _add(info, "headline", _capped(message or f"Flood {severity_key}", 160))
    _add(info, "description", _capped(
        message or "Automated flood alert issued by FloodOps."))
    reach = dispatch.get("total_reach_estimate")
    if reach:
        param = ET.SubElement(info, f"{{{CAP_NS}}}parameter")
        _add(param, "valueName", "estimatedReach")
        _add(param, "value", _capped(reach, 32))

    # Area from the first broadcast's zone polygon (lat,lon pairs per CAP).
    if broadcasts and isinstance(broadcasts[0], dict):
        geom = (broadcasts[0].get("zone_polygon") or {})
        coords = geom.get("coordinates") or []
        ring = coords[0] if coords and isinstance(coords[0], list) else []
        if ring and all(isinstance(p, (list, tuple)) and len(p) >= 2 for p in ring):
            area = ET.SubElement(info, f"{{{CAP_NS}}}area")
            _add(area, "areaDesc", _capped(
                dispatch.get("event_id", "affected flood zone"), 256))
            _add(area, "polygon", _capped(
                " ".join(f"{p[1]:.4f},{p[0]:.4f}" for p in ring), 4096))

    return ET.tostring(alert, encoding="unicode", xml_declaration=True)
