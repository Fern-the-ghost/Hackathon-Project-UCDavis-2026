"""Grid sampling helpers."""

import pytest
import numpy as np

from backend.physics import bilinear_sample_db


def test_bilinear_matches_corners():
    grid = np.array(
        [
            [0.0, 10.0],
            [20.0, 30.0],
        ],
        dtype=np.float64,
    )
    width_m = 2.0
    height_m = 2.0
    assert bilinear_sample_db(grid, 0.5, 0.5, width_m, height_m) == pytest.approx(
        0.0, abs=1e-9
    )
    assert bilinear_sample_db(grid, 1.5, 1.5, width_m, height_m) == pytest.approx(
        30.0, abs=1e-9
    )
