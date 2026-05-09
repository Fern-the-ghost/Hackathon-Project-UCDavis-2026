"""
Overpass API ingest for land-use style polygons (§2 OSM ingest sketch).

Fetches ``way`` features carrying ``landuse``, ``amenity``, ``leisure``, ``building``,
or ``shop`` tags inside the bbox (south,west,north,east).
"""

from __future__ import annotations

import textwrap
from typing import Any

import httpx

from pydantic import BaseModel, Field, model_validator

DEFAULT_OVERPASS_URL = "https://overpass-api.de/api/interpreter"

# Overpass returns HTTP 406 for the default ``python-httpx`` user-agent string.
_OVERPASS_HEADERS = {
    "User-Agent": "UrbanAcoustic/0.2 (OSM ingest; https://openstreetmap.org/copyright)",
    "Accept": "*/*",
}


class OSMBoundingBox(BaseModel):
    """WGS84 bounding box (degrees)."""

    min_lon: float = Field(..., description="Western edge")
    min_lat: float = Field(..., description="Southern edge")
    max_lon: float = Field(..., description="Eastern edge")
    max_lat: float = Field(..., description="Northern edge")

    @model_validator(mode="after")
    def validate_extent(self) -> OSMBoundingBox:
        if self.max_lon <= self.min_lon or self.max_lat <= self.min_lat:
            raise ValueError("Invalid bbox: expected positive lon/lat spans.")
        return self


# Santa Clara County — Silicon Valley “data center alley” along CA-237 / Great America vicinity.
SANTA_CLARA_DATA_CENTER_ALLEY_BBOX = OSMBoundingBox(
    min_lon=-122.02,
    min_lat=37.36,
    max_lon=-121.965,
    max_lat=37.415,
)


def build_overpass_query(bbox: OSMBoundingBox) -> str:
    """Union query for ways bearing zoning-relevant tags; geometry attached."""
    s, w, n, e = bbox.min_lat, bbox.min_lon, bbox.max_lat, bbox.max_lon
    # fmt: off
    return textwrap.dedent(
        f"""
        [out:json][timeout:120];
        (
          way["landuse"]({s},{w},{n},{e});
          way["amenity"]({s},{w},{n},{e});
          way["leisure"]({s},{w},{n},{e});
          way["building"]({s},{w},{n},{e});
          way["shop"]({s},{w},{n},{e});
        );
        out tags geom;
        """
    ).strip()
    # fmt: on


def fetch_osm_zoning_ways(
    bbox: OSMBoundingBox,
    *,
    overpass_url: str = DEFAULT_OVERPASS_URL,
    timeout_s: float = 120.0,
) -> list[dict[str, Any]]:
    """
    Query Overpass for zoning-related ways and return raw ``elements`` list.

    Raises ``httpx.HTTPError`` on transport/API failures.
    """
    query = build_overpass_query(bbox)
    with httpx.Client(timeout=timeout_s, headers=_OVERPASS_HEADERS) as client:
        resp = client.post(overpass_url, content=query)
        resp.raise_for_status()
        payload = resp.json()

    elements = payload.get("elements")
    if not isinstance(elements, list):
        return []
    return [el for el in elements if isinstance(el, dict)]


def fetch_zoning_features(
    bbox: OSMBoundingBox,
    *,
    overpass_url: str = DEFAULT_OVERPASS_URL,
    timeout_s: float = 120.0,
) -> list[dict[str, Any]]:
    """Fetch OSM ways then normalize to zoning ``features`` (polygon + bucket)."""
    from backend.services.zoning_mapper import features_from_overpass

    raw = fetch_osm_zoning_ways(bbox, overpass_url=overpass_url, timeout_s=timeout_s)
    return features_from_overpass(raw)


async def fetch_osm_zoning_ways_async(
    bbox: OSMBoundingBox,
    *,
    overpass_url: str = DEFAULT_OVERPASS_URL,
    timeout_s: float = 120.0,
) -> list[dict[str, Any]]:
    """Async variant for ASGI stacks."""
    query = build_overpass_query(bbox)
    async with httpx.AsyncClient(timeout=timeout_s, headers=_OVERPASS_HEADERS) as client:
        resp = await client.post(overpass_url, content=query)
        resp.raise_for_status()
        payload = resp.json()
    elements = payload.get("elements")
    if not isinstance(elements, list):
        return []
    return [el for el in elements if isinstance(el, dict)]
