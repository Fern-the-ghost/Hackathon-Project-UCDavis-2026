"""
§6 OSM tag → zoning bucket mapping plus Phase B explicit tag rules.

Classification priority for overlapping polygons (first match wins):
Residential → Public → Commercial → Industrial.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from shapely.geometry import Polygon, shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union
from shapely.prepared import prep


class ZoningBucket(str, Enum):
    RESIDENTIAL = "RESIDENTIAL"
    COMMERCIAL = "COMMERCIAL"
    PUBLIC = "PUBLIC"
    INDUSTRIAL = "INDUSTRIAL"
    OTHER = "OTHER"


_BUCKET_PRIORITY: tuple[ZoningBucket, ...] = (
    ZoningBucket.RESIDENTIAL,
    ZoningBucket.PUBLIC,
    ZoningBucket.COMMERCIAL,
    ZoningBucket.INDUSTRIAL,
)


def classify_osm_tags(tags: dict[str, Any]) -> ZoningBucket | None:
    """
    Map OSM tags to a zoning bucket. Returns ``None`` if this feature should not
    participate in land-use zoning (unclassified tags).

    Phase B explicit signals:
    - Residential: ``landuse=residential``, ``building=apartments``
    - Commercial: ``landuse=commercial``, any ``shop=*``
    - Public: ``amenity=school``, ``amenity=hospital``, ``leisure=park``

    Extended §6 heuristics:
    ``residential=*``, ``place=suburb``, ``amenity=marketplace``, ``landuse=civic``,
    ``landuse=industrial``, ``man_made=works``.
    """
    if not tags:
        return None

    def gv(key: str) -> str | None:
        v = tags.get(key)
        if v is None:
            return None
        return str(v).strip().lower() if str(v).strip() else None

    landuse = gv("landuse")
    amenity = gv("amenity")
    leisure = gv("leisure")
    building = gv("building")
    man_made = gv("man_made")
    residential = gv("residential")
    place = gv("place")

    # Residential
    if landuse == "residential":
        return ZoningBucket.RESIDENTIAL
    if building == "apartments":
        return ZoningBucket.RESIDENTIAL
    if residential is not None and residential != "":
        return ZoningBucket.RESIDENTIAL
    if place == "suburb":
        return ZoningBucket.RESIDENTIAL

    # Public (before commercial where civic overlaps concern)
    if landuse == "civic":
        return ZoningBucket.PUBLIC
    if amenity in {"school", "hospital"}:
        return ZoningBucket.PUBLIC
    if leisure == "park":
        return ZoningBucket.PUBLIC

    # Commercial
    if landuse == "commercial":
        return ZoningBucket.COMMERCIAL
    if amenity == "marketplace":
        return ZoningBucket.COMMERCIAL
    if gv("shop") is not None:
        return ZoningBucket.COMMERCIAL

    # Industrial §6
    if landuse == "industrial":
        return ZoningBucket.INDUSTRIAL
    if man_made == "works":
        return ZoningBucket.INDUSTRIAL

    return None


def way_geometry_to_polygon(element: dict[str, Any]) -> Polygon | None:
    """Build a Shapely polygon from an Overpass ``way`` with ``geometry`` list."""
    geom = element.get("geometry")
    if not geom or len(geom) < 3:
        return None

    coords = [(float(p["lon"]), float(p["lat"])) for p in geom]
    if coords[0] != coords[-1]:
        coords = coords + [coords[0]]
    try:
        poly = Polygon(coords)
        if not poly.is_valid:
            poly = poly.buffer(0)
        if poly.is_empty or poly.geom_type != "Polygon":
            return None
        return poly
    except (KeyError, TypeError, ValueError):
        return None


def features_from_overpass(elements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalize Overpass elements to ``{"tags", "polygon"}`` records."""
    out: list[dict[str, Any]] = []
    for el in elements:
        if el.get("type") != "way":
            continue
        tags = el.get("tags") or {}
        bucket = classify_osm_tags(tags)
        if bucket is None:
            continue
        poly = way_geometry_to_polygon(el)
        if poly is None:
            continue
        out.append({"tags": tags, "bucket": bucket, "polygon": poly})
    return out


def bucket_polygons(features: list[dict[str, Any]]) -> dict[ZoningBucket, list[Polygon]]:
    grouped: dict[ZoningBucket, list[Polygon]] = {b: [] for b in ZoningBucket if b != ZoningBucket.OTHER}
    for f in features:
        b = f["bucket"]
        grouped[b].append(f["polygon"])
    return grouped


def merge_bucket_geometries(
    grouped: dict[ZoningBucket, list[Polygon]],
) -> dict[ZoningBucket, BaseGeometry]:
    """Union polygons per bucket for fewer prepared predicates."""
    merged: dict[ZoningBucket, BaseGeometry] = {}
    for b, polys in grouped.items():
        if not polys:
            continue
        try:
            merged[b] = unary_union(polys)
        except Exception:
            merged[b] = unary_union([p.buffer(0) for p in polys])
    return merged


def classify_lonlat(
    lon: float,
    lat: float,
    merged: dict[ZoningBucket, BaseGeometry],
) -> ZoningBucket:
    """Point-in-polygon against merged bucket geometries (§4.3)."""
    from shapely.geometry import Point

    pt = Point(lon, lat)
    for bucket in _BUCKET_PRIORITY:
        geom = merged.get(bucket)
        if geom is None or geom.is_empty:
            continue
        if prep(geom).covers(pt):
            return bucket
    return ZoningBucket.OTHER


def rasterize_zoning_buckets(
    lon_grid: Any,
    lat_grid: Any,
    merged: dict[ZoningBucket, BaseGeometry],
) -> Any:
    """Vectorized zoning labels at cell centers (same shape as lon/lat grids)."""
    import numpy as np

    lon_grid = np.asarray(lon_grid, dtype=np.float64)
    lat_grid = np.asarray(lat_grid, dtype=np.float64)
    flat_lon = lon_grid.ravel()
    flat_lat = lat_grid.ravel()
    labels = np.empty(flat_lon.shape[0], dtype=object)
    for i in range(flat_lon.shape[0]):
        labels[i] = classify_lonlat(float(flat_lon[i]), float(flat_lat[i]), merged).value
    return labels.reshape(lon_grid.shape)


def geojson_fc_to_features(fc: dict[str, Any]) -> list[dict[str, Any]]:
    """Optional: parse GeoJSON FeatureCollection from disk/cache."""
    feats = fc.get("features") or []
    out: list[dict[str, Any]] = []
    for feat in feats:
        props = feat.get("properties") or {}
        tags = props.get("tags") if isinstance(props.get("tags"), dict) else props
        bucket = classify_osm_tags(tags if isinstance(tags, dict) else {})
        if bucket is None:
            continue
        geom = shape(feat["geometry"])
        if geom.geom_type == "Polygon":
            poly = geom
        elif geom.geom_type == "MultiPolygon":
            poly = max(geom.geoms, key=lambda g: g.area)
        else:
            continue
        out.append({"tags": tags, "bucket": bucket, "polygon": poly})
    return out
