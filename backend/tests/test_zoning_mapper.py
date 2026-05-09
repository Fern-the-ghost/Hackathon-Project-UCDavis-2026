"""§6 zoning classification tests."""

from shapely.geometry import Point, Polygon

from backend.services.zoning_mapper import (
    ZoningBucket,
    bucket_polygons,
    classify_lonlat,
    classify_osm_tags,
    features_from_overpass,
    merge_bucket_geometries,
)


def test_classify_explicit_public_signals():
    assert classify_osm_tags({"amenity": "school"}) == ZoningBucket.PUBLIC
    assert classify_osm_tags({"amenity": "hospital"}) == ZoningBucket.PUBLIC
    assert classify_osm_tags({"leisure": "park"}) == ZoningBucket.PUBLIC


def test_classify_explicit_commercial_shop_any():
    assert classify_osm_tags({"shop": "supermarket"}) == ZoningBucket.COMMERCIAL
    assert classify_osm_tags({"landuse": "commercial"}) == ZoningBucket.COMMERCIAL


def test_classify_explicit_residential():
    assert classify_osm_tags({"landuse": "residential"}) == ZoningBucket.RESIDENTIAL
    assert classify_osm_tags({"building": "apartments"}) == ZoningBucket.RESIDENTIAL


def test_industrial_tags():
    assert classify_osm_tags({"landuse": "industrial"}) == ZoningBucket.INDUSTRIAL
    assert classify_osm_tags({"man_made": "works"}) == ZoningBucket.INDUSTRIAL


def test_point_in_polygon_priority_residential_over_commercial():
    residential = Polygon([(0, 0), (2, 0), (2, 2), (0, 2)])
    commercial = Polygon([(0.5, 0.5), (1.5, 0.5), (1.5, 1.5), (0.5, 1.5)])
    merged = merge_bucket_geometries(
        {
            ZoningBucket.COMMERCIAL: [commercial],
            ZoningBucket.RESIDENTIAL: [residential],
        }
    )
    pt_inside_both = Point(1.0, 1.0)
    assert classify_lonlat(pt_inside_both.x, pt_inside_both.y, merged) == ZoningBucket.RESIDENTIAL


def test_overpass_way_roundtrip_minimal():
    elements = [
        {
            "type": "way",
            "id": 1,
            "tags": {"landuse": "residential"},
            "geometry": [
                {"lat": 0.0, "lon": 0.0},
                {"lat": 0.0, "lon": 1.0},
                {"lat": 1.0, "lon": 1.0},
                {"lat": 1.0, "lon": 0.0},
                {"lat": 0.0, "lon": 0.0},
            ],
        }
    ]
    feats = features_from_overpass(elements)
    assert len(feats) == 1
    merged = merge_bucket_geometries(bucket_polygons(feats))
    assert classify_lonlat(0.5, 0.5, merged) == ZoningBucket.RESIDENTIAL
