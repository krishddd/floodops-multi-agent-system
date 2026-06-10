"""Map layer GeoJSON endpoints — serve data for deck.gl layers."""

from __future__ import annotations

import random

from fastapi import APIRouter

from floodops.api.app import get_latest_urban
from floodops.models.geo import GeoJsonFeature, GeoJsonFeatureCollection, GeoJsonGeometry

router = APIRouter()


def _kathmandu_flood_zones() -> GeoJsonFeatureCollection:
    """Generate demo flood zones around Kathmandu Valley."""
    random.seed(42)
    zones = [
        {"name": "Kirtipur Ward 5", "coords": [[[85.28, 27.67], [85.32, 27.67], [85.32, 27.70], [85.28, 27.70], [85.28, 27.67]]], "risk": 0.85, "confidence": 0.78, "agreement": 38, "depth": 2.1},
        {"name": "Bagmati Corridor", "coords": [[[85.30, 27.70], [85.35, 27.70], [85.35, 27.73], [85.30, 27.73], [85.30, 27.70]]], "risk": 0.92, "confidence": 0.89, "agreement": 44, "depth": 3.4},
        {"name": "Lalitpur Central", "coords": [[[85.31, 27.66], [85.35, 27.66], [85.35, 27.69], [85.31, 27.69], [85.31, 27.66]]], "risk": 0.55, "confidence": 0.62, "agreement": 28, "depth": 0.8},
        {"name": "Patan Industrial", "coords": [[[85.32, 27.68], [85.37, 27.68], [85.37, 27.71], [85.32, 27.71], [85.32, 27.68]]], "risk": 0.72, "confidence": 0.71, "agreement": 35, "depth": 1.5},
        {"name": "Bhaktapur Old Town", "coords": [[[85.42, 27.67], [85.45, 27.67], [85.45, 27.69], [85.42, 27.69], [85.42, 27.67]]], "risk": 0.40, "confidence": 0.55, "agreement": 22, "depth": 0.4},
    ]

    features = []
    for i, z in enumerate(zones):
        features.append(GeoJsonFeature(
            id=f"zone_{i+1}",
            geometry=GeoJsonGeometry(type="Polygon", coordinates=z["coords"]),
            properties={"zone_name": z["name"], "risk_score": z["risk"], "confidence": z["confidence"],
                        "ensemble_agreement": z["agreement"], "total_members": 50, "predicted_depth_m": z["depth"],
                        "population": random.randint(3000, 25000), "risk_level": "CRITICAL" if z["risk"] > 0.8 else "HIGH" if z["risk"] > 0.6 else "MEDIUM"},
        ))
    return GeoJsonFeatureCollection(features=features)


@router.get("/flood-zones")
async def get_flood_zones():
    """Flood-zone polygons for the GeoJsonLayer.

    Geometry comes from the Kathmandu demo footprints (the urban model emits
    zone risk without polygons); when a live UrbanRiskReport exists, its
    per-zone risk_score / confidence / reasoning are merged onto the polygons
    so the map and "why" cards reflect live agent reasoning.
    """
    fc = _kathmandu_flood_zones()
    urban = get_latest_urban()
    if urban and urban.get("zones"):
        live = urban["zones"]
        for i, feature in enumerate(fc.features):
            if i < len(live):
                z = live[i]
                feature.properties.update({
                    "risk_score": z.get("risk_score", feature.properties.get("risk_score")),
                    "confidence": z.get("confidence", feature.properties.get("confidence")),
                    "risk_level": z.get("risk_level", feature.properties.get("risk_level")),
                    "predicted_depth_m": z.get("predicted_depth_m",
                                               feature.properties.get("predicted_depth_m")),
                    "population": z.get("population", feature.properties.get("population")),
                    "reasoning": z.get("reasoning"),
                    "source": "live",
                })
    return fc.model_dump()


@router.get("/flood-depth")
async def get_flood_depth():
    """30m grid cells with depth for ColumnLayer extrusion."""
    random.seed(99)
    features = []
    for _i in range(80):
        lat = 27.68 + random.uniform(-0.05, 0.05)
        lng = 85.32 + random.uniform(-0.05, 0.05)
        depth = max(0.1, random.lognormvariate(0.3, 0.7))
        features.append(GeoJsonFeature(
            geometry=GeoJsonGeometry(type="Point", coordinates=[lng, lat]),
            properties={"depth_median_m": round(depth, 2), "depth_p5_m": round(depth * 0.3, 2),
                        "depth_p95_m": round(depth * 2.1, 2), "cell_size_m": 30},
        ))
    return GeoJsonFeatureCollection(features=features).model_dump()


@router.get("/sensors")
async def get_sensors():
    """Sensor locations for ScatterplotLayer."""
    sensors = [
        {"id": "USGS-BG001", "name": "Bagmati at Chobar", "lat": 27.66, "lng": 85.30, "type": "gauge", "status": "critical", "value": 4.2, "unit": "m", "source": "USGS", "cadence": "15 min"},
        {"id": "USGS-BG002", "name": "Bagmati at Pashupati", "lat": 27.71, "lng": 85.35, "type": "gauge", "status": "elevated", "value": 3.1, "unit": "m", "source": "USGS", "cadence": "15 min"},
        {"id": "NWS-KTM01", "name": "TIA Weather Station", "lat": 27.70, "lng": 85.36, "type": "weather", "status": "normal", "value": 142, "unit": "mm/24h", "source": "NWS", "cadence": "15 min"},
        {"id": "SM-KTM01", "name": "Soil Moisture Kathmandu", "lat": 27.72, "lng": 85.32, "type": "soil", "status": "elevated", "value": 85, "unit": "%", "source": "CDS", "cadence": "daily"},
    ]
    features = [GeoJsonFeature(geometry=GeoJsonGeometry(type="Point", coordinates=[s["lng"], s["lat"]]),
                                properties=s) for s in sensors]
    return GeoJsonFeatureCollection(features=features).model_dump()


@router.get("/evacuation-routes")
async def get_evacuation_routes():
    """Evacuation arcs for ArcLayer — origin (danger) to destination (shelter)."""
    routes = [
        {"origin": [85.30, 27.68], "dest": [85.28, 27.72], "name": "Kirtipur → Kirtipur HS", "population": 4200, "time_min": 18},
        {"origin": [85.32, 27.71], "dest": [85.36, 27.74], "name": "Bagmati → Budhanilkantha", "population": 8500, "time_min": 35},
        {"origin": [85.33, 27.67], "dest": [85.38, 27.70], "name": "Lalitpur → Bhaktapur School", "population": 3100, "time_min": 22},
    ]
    return {"routes": routes}


@router.get("/glacial-lakes")
async def get_glacial_lakes():
    """Glacial lake data for PolygonLayer with extrusion."""
    lakes = [
        {"id": "GL001", "name": "Tsho Rolpa", "lat": 27.862, "lng": 86.477, "integrity": 0.45, "volume_m3": 80_000_000, "risk": "HIGH"},
        {"id": "GL002", "name": "Imja Tsho", "lat": 27.899, "lng": 86.931, "integrity": 0.72, "volume_m3": 61_700_000, "risk": "MEDIUM"},
        {"id": "GL003", "name": "Thulagi Lake", "lat": 28.490, "lng": 84.440, "integrity": 0.28, "volume_m3": 35_000_000, "risk": "CRITICAL"},
    ]
    features = [GeoJsonFeature(
        id=lk["id"],
        geometry=GeoJsonGeometry(type="Polygon", coordinates=[[[lk["lng"]-0.01, lk["lat"]-0.005], [lk["lng"]+0.01, lk["lat"]-0.005],
                                                                [lk["lng"]+0.01, lk["lat"]+0.005], [lk["lng"]-0.01, lk["lat"]+0.005], [lk["lng"]-0.01, lk["lat"]-0.005]]]),
        properties=lk,
    ) for lk in lakes]
    return GeoJsonFeatureCollection(features=features).model_dump()


@router.get("/population-risk")
async def get_population_risk():
    """Population-at-risk data for HexagonLayer."""
    random.seed(555)
    points = []
    for _ in range(200):
        points.append({"lat": 27.68 + random.gauss(0, 0.03), "lng": 85.32 + random.gauss(0, 0.03),
                        "population": random.randint(50, 500), "risk_score": round(random.uniform(0.2, 0.95), 2)})
    return {"points": points}
