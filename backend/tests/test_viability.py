"""§4.3 viability scoring tests."""

from datetime import datetime, timezone

import pytest

from backend.services.zoning_mapper import ZoningBucket
from backend.viability import (
    compute_viability_scores,
    is_clock_nighttime,
    resolve_is_nighttime,
)


def test_nighttime_exactly_ten_db_on_predicted_only():
    scores_day = compute_viability_scores(
        predicted_db_physical=40.0,
        is_nighttime=False,
        threshold_db=45.0,
        zoning=ZoningBucket.OTHER,
    )
    scores_night = compute_viability_scores(
        predicted_db_physical=40.0,
        is_nighttime=True,
        threshold_db=45.0,
        zoning=ZoningBucket.OTHER,
    )
    assert scores_night.predicted_db_physical == scores_day.predicted_db_physical
    assert scores_night.predicted_db == scores_day.predicted_db + 10.0
    assert scores_night.night_db_penalty_applied == 10.0


def test_exceedance_uses_predicted_db_with_night_penalty():
    scores = compute_viability_scores(
        predicted_db_physical=38.0,
        is_nighttime=True,
        threshold_db=45.0,
        zoning=ZoningBucket.OTHER,
    )
    assert scores.predicted_db == 48.0
    assert scores.exceedance_db == pytest.approx(3.0)


def test_resolve_nighttime_precedence():
    flag, _ = resolve_is_nighttime(
        explicit=None,
        local_timestamp=datetime(2026, 5, 9, 23, tzinfo=timezone.utc),
        timezone=None,
        clock_time=None,
    )
    assert flag is True

    flag2, _ = resolve_is_nighttime(
        explicit=None,
        local_timestamp=None,
        timezone=None,
        clock_time=None,
    )
    assert flag2 is False

    flag_force_day, _ = resolve_is_nighttime(
        explicit=False,
        local_timestamp=datetime(2026, 5, 9, 23, tzinfo=timezone.utc),
        timezone=None,
        clock_time=None,
    )
    assert flag_force_day is False

    flag_force_night, ctx3 = resolve_is_nighttime(
        explicit=True,
        local_timestamp=datetime(2026, 5, 9, 12, tzinfo=timezone.utc),
        timezone=None,
        clock_time=None,
    )
    assert flag_force_night is True
    assert ctx3["is_nighttime"] is True


def test_clock_window_edges():
    assert is_clock_nighttime(21, 59) is False
    assert is_clock_nighttime(22, 0) is True
    assert is_clock_nighttime(6, 59) is True
    assert is_clock_nighttime(7, 0) is False


def test_resolve_timezone_clock_time():
    flag, ctx = resolve_is_nighttime(
        explicit=None,
        local_timestamp=None,
        timezone="America/Los_Angeles",
        clock_time="23:15",
    )
    assert flag is True
    assert ctx["timezone"] == "America/Los_Angeles"
