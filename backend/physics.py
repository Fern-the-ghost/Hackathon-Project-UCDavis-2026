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
    if cell_size_m <= 0:
        raise ValueError("cell_size_m must be positive")
    if not sources:
        raise ValueError("at least one source is required")

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

    # Cell centers in meters (south-west origin)
    xs_half = (np.arange(n_cols) + 0.5) * (width_m / n_cols)
    ys_half = (np.arange(n_rows) + 0.5) * (height_m / n_rows)
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
