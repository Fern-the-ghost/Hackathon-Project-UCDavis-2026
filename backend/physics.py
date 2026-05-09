"""
§3 acoustic model: ground-level decay, dual weighting, energy addition.

L_ground = L_source - 20 log10(d) - A_eff  (§3.2)
A_eff = A_abs for dBA; A_eff = 0.5 * A_abs for dBC (§3.2)
L_total = 10 log10(sum_i 10^(L_i/10)) (§3.4)
"""

from __future__ import annotations

import math
from enum import Enum
from typing import NamedTuple

import numpy as np


class AcousticWeighting(str, Enum):
    """Active listening curve for absorption in decay (§3.2)."""

    DBA = "DBA"
    DBC = "DBC"


def effective_absorption(A_abs: float, weighting: AcousticWeighting) -> float:
    """Nominal urban absorption A_abs → effective term in §3.2 decay."""
    if weighting == AcousticWeighting.DBC:
        return 0.5 * A_abs
    return A_abs


def ground_level_db(
    L_source_db: float,
    distance_m: float,
    A_abs: float,
    weighting: AcousticWeighting,
) -> float:
    """
    Single source → receiver SPL (dB) per §3.2.
    distance_m: horizontal separation in projected meters.
    """
    A_eff = effective_absorption(A_abs, weighting)
    d = max(float(distance_m), 1e-9)
    return L_source_db - 20.0 * math.log10(d) - A_eff


def energy_sum_db(levels_db: np.ndarray) -> np.ndarray:
    """
    Incoherent addition over last axis: 10 log10(sum 10^(L/10)).

    levels_db: shape (..., n_sources); returns shape (...).
    """
    levels_db = np.asarray(levels_db, dtype=np.float64)
    intensity = np.sum(np.power(10.0, levels_db / 10.0), axis=-1)
    intensity = np.maximum(intensity, 1e-20)
    return 10.0 * np.log10(intensity)


def lonlat_to_local_meters(
    lon: np.ndarray,
    lat: np.ndarray,
    lon0: float,
    lat0: float,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Local tangent-plane meters east/north from (lon0, lat0).
    Adequate for hackathon-scale bboxes; §2.3 prefers full CRS projection later.
    """
    R = 6371000.0
    phi0 = math.radians(lat0)
    lon_r = np.radians(np.asarray(lon, dtype=np.float64))
    lat_r = np.radians(np.asarray(lat, dtype=np.float64))
    x = (lon_r - math.radians(lon0)) * R * math.cos(phi0)
    y = (lat_r - math.radians(lat0)) * R
    return x, y


class NoiseSourceInput(NamedTuple):
    lon: float
    lat: float
    reference_level_db: float


def compute_metric_layout(
    min_lon: float,
    min_lat: float,
    max_lon: float,
    max_lat: float,
    cell_size_m: float,
) -> tuple[float, float, int, int, np.ndarray, np.ndarray]:
    """Metric bbox extent (m), grid counts, and 1D cell-center axes from SW corner."""
    if cell_size_m <= 0:
        raise ValueError("cell_size_m must be positive")

    lon0, lat0 = min_lon, min_lat

    # Metric extent from SW corner: east along south edge, north along west edge (§2.3).
    width_m = float(
        lonlat_to_local_meters(
            np.array([max_lon]),
            np.array([min_lat]),
            lon0,
            lat0,
        )[0][0]
    )
    height_m = float(
        lonlat_to_local_meters(
            np.array([min_lon]),
            np.array([max_lat]),
            lon0,
            lat0,
        )[1][0]
    )

    n_cols = max(1, int(math.ceil(width_m / cell_size_m)))
    n_rows = max(1, int(math.ceil(height_m / cell_size_m)))

    xs_half = (np.arange(n_cols) + 0.5) * (width_m / n_cols)
    ys_half = (np.arange(n_rows) + 0.5) * (height_m / n_rows)
    return width_m, height_m, n_rows, n_cols, xs_half, ys_half


def local_meters_to_lonlat(
    x_m: np.ndarray | float,
    y_m: np.ndarray | float,
    lon0: float,
    lat0: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Inverse of ``lonlat_to_local_meters`` for tangent-plane offsets (meters east/north)."""
    R = 6371000.0
    phi0 = math.radians(lat0)
    xm = np.asarray(x_m, dtype=np.float64)
    ym = np.asarray(y_m, dtype=np.float64)
    lon = lon0 + np.degrees(xm / (R * math.cos(phi0)))
    lat = lat0 + np.degrees(ym / R)
    return lon, lat


def bilinear_sample_db(
    grid_db: np.ndarray,
    x_m: float,
    y_m: float,
    width_m: float,
    height_m: float,
) -> float:
    """Sample ``grid_db`` (shape rows×cols) at metric offset (x_m, y_m) from SW corner."""
    n_rows, n_cols = grid_db.shape
    if n_rows < 1 or n_cols < 1:
        raise ValueError("grid_db must be non-empty")

    dx = width_m / n_cols
    dy = height_m / n_rows
    x_clamped = min(max(x_m, 0.0), width_m)
    y_clamped = min(max(y_m, 0.0), height_m)

    col_c = x_clamped / dx - 0.5
    row_c = y_clamped / dy - 0.5

    c0 = int(math.floor(col_c))
    r0 = int(math.floor(row_c))
    c1 = min(c0 + 1, n_cols - 1)
    r1 = min(r0 + 1, n_rows - 1)
    c0 = max(c0, 0)
    r0 = max(r0, 0)

    tc = col_c - c0 if n_cols > 1 else 0.0
    tr = row_c - r0 if n_rows > 1 else 0.0
    tc = min(max(tc, 0.0), 1.0)
    tr = min(max(tr, 0.0), 1.0)

    q00 = float(grid_db[r0, c0])
    q01 = float(grid_db[r0, c1])
    q10 = float(grid_db[r1, c0])
    q11 = float(grid_db[r1, c1])
    q0 = q00 * (1 - tc) + q01 * tc
    q1 = q10 * (1 - tc) + q11 * tc
    return float(q0 * (1 - tr) + q1 * tr)


def lonlat_to_metric_offset(lon: float, lat: float, lon0: float, lat0: float) -> tuple[float, float]:
    """Single-point metric offset (east_m, north_m) from ``(lon0, lat0)``."""
    xe, yn = lonlat_to_local_meters(np.array([lon]), np.array([lat]), lon0, lat0)
    return float(xe[0]), float(yn[0])


def compute_grid_levels_db(
    min_lon: float,
    min_lat: float,
    max_lon: float,
    max_lat: float,
    cell_size_m: float,
    sources: list[NoiseSourceInput],
    weighting: AcousticWeighting,
    A_abs: float = 0.0,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Build a metric-aligned grid over the bbox and return L_total [dB] per cell.

    Returns:
        L_grid: shape (n_rows, n_cols)
        xs_center_m: 1d cell-center x (m east from origin at min_lon, min_lat)
        ys_center_m: 1d cell-center y (m north)
    """
    if not sources:
        raise ValueError("at least one source is required")

    lon0, lat0 = min_lon, min_lat
    width_m, height_m, n_rows, n_cols, xs_half, ys_half = compute_metric_layout(
        min_lon, min_lat, max_lon, max_lat, cell_size_m
    )

    # Cell centers in meters (south-west origin)
    CX, CY = np.meshgrid(xs_half, ys_half)

    sx_m = []
    sy_m = []
    Lrefs = []
    for s in sources:
        x_s, y_s = lonlat_to_local_meters(
            np.array([s.lon]),
            np.array([s.lat]),
            lon0,
            lat0,
        )
        sx_m.append(float(x_s[0]))
        sy_m.append(float(y_s[0]))
        Lrefs.append(s.reference_level_db)

    sx_m = np.array(sx_m, dtype=np.float64)
    sy_m = np.array(sy_m, dtype=np.float64)
    Lrefs = np.array(Lrefs, dtype=np.float64)

    # Distances: each source to each cell
    # stacks shape (n_sources, n_rows, n_cols)
    dx = CX[np.newaxis, :, :] - sx_m[:, np.newaxis, np.newaxis]
    dy = CY[np.newaxis, :, :] - sy_m[:, np.newaxis, np.newaxis]
    dist = np.sqrt(dx * dx + dy * dy)

    A_eff = effective_absorption(A_abs, weighting)
    levels = Lrefs[:, np.newaxis, np.newaxis] - 20.0 * np.log10(
        np.maximum(dist, 1e-9)
    ) - A_eff

    levels_stacked = np.moveaxis(levels, 0, -1)
    L_grid = energy_sum_db(levels_stacked)
    return L_grid, xs_half, ys_half
