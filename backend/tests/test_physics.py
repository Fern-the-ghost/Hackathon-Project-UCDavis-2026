"""Physics golden checks per §3.4 / §3.6."""

import math

import numpy as np

from backend.physics import (
    AcousticWeighting,
    NoiseSourceInput,
    compute_grid_levels_db,
    effective_absorption,
    energy_sum_db,
    ground_level_db,
    lonlat_to_local_meters,
)


def test_energy_sum_two_equal_sources_plus_3_db():
    """Two equal contributors at the same receiver → +10·log10(2) ≈ +3.01 dB (§3.4)."""
    L_each = ground_level_db(
        L_source_db=90.0,
        distance_m=50.0,
        A_abs=0.0,
        weighting=AcousticWeighting.DBA,
    )
    stacked = np.array([L_each, L_each])
    L_total = energy_sum_db(stacked)
    expected_delta = 10.0 * math.log10(2.0)
    assert math.isclose(L_total, L_each + expected_delta, rel_tol=1e-9, abs_tol=1e-6)


def test_two_equal_sources_100m_apart_midpoint_plus_3_db_grid():
    """
    Two equal industrial-style sources 100 m apart: midpoint sees +3 dB vs one source alone.

    Uses the same reference_level_db for both (50 MW is scenario metadata; SPL follows §3.2).
    """
    ref_db = 95.0
    A_abs = 2.5

    # SW corner at origin; sources at (0,0) and (100,0) m. One column spans full width so the
    # cell center is exactly x = 50 m (perpendicular bisector), giving +3 dB vs a single source (§3.4).
    cell = 100.0
    width_m = 100.0
    height_m = 60.0
    lat0 = 37.35
    lon0 = -121.97
    R = 6371000.0
    phi0 = math.radians(lat0)
    # Exact 100 m easting → lon delta consistent with backend.physics.lonlat_to_local_meters
    delta_lon_deg = math.degrees(100.0 / (R * math.cos(phi0)))
    meters_per_deg_lat = 111_320.0  # for northern bbox edge only
    dlat = height_m / meters_per_deg_lat
    dlon = width_m / (R * math.cos(phi0)) * (180.0 / math.pi)

    min_lon, min_lat = lon0, lat0
    max_lon, max_lat = lon0 + dlon, lat0 + dlat

    s1 = NoiseSourceInput(lon=min_lon, lat=min_lat, reference_level_db=ref_db)
    s2 = NoiseSourceInput(lon=min_lon + delta_lon_deg, lat=min_lat, reference_level_db=ref_db)

    L_both, xs_c, ys_c = compute_grid_levels_db(
        min_lon,
        min_lat,
        max_lon,
        max_lat,
        cell,
        [s1, s2],
        AcousticWeighting.DBA,
        A_abs=A_abs,
    )

    row, col = 0, 0
    assert math.isclose(float(xs_c[col]), 50.0, rel_tol=0.0, abs_tol=1e-6)
    L_mid_both = float(L_both[row, col])

    L_one, _, _ = compute_grid_levels_db(
        min_lon,
        min_lat,
        max_lon,
        max_lat,
        cell,
        [s1],
        AcousticWeighting.DBA,
        A_abs=A_abs,
    )
    L_mid_one = float(L_one[row, col])

    delta = L_mid_both - L_mid_one
    assert math.isclose(delta, 10.0 * math.log10(2.0), rel_tol=0.005, abs_tol=0.02)


def test_dbc_halves_absorption_coefficient():
    assert effective_absorption(4.0, AcousticWeighting.DBA) == 4.0
    assert effective_absorption(4.0, AcousticWeighting.DBC) == 2.0

    d_m = 80.0
    L_ref = 88.0
    A_abs = 6.0
    L_a = ground_level_db(L_ref, d_m, A_abs, AcousticWeighting.DBA)
    L_c = ground_level_db(L_ref, d_m, A_abs, AcousticWeighting.DBC)
    assert math.isclose(L_c - L_a, 0.5 * A_abs)


def test_lonlat_roundtrip_extent_reasonable():
    lon0, lat0 = -122.0, 37.4
    xe, ye = lonlat_to_local_meters(
        np.array([lon0 + 0.01]),
        np.array([lat0 + 0.01]),
        lon0,
        lat0,
    )
    assert xe[0] > 0 and ye[0] > 0
