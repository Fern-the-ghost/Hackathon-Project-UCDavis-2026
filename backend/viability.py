"""§4 development viability scoring on top of modeled SPL grids."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from backend.physics import AcousticWeighting
from backend.services.zoning_mapper import ZoningBucket

NIGHT_WINDOW_LABEL = "22:00-07:00"
NIGHT_DB_PENALTY = 10.0

# §4.3 exposure penalty tuning — monotone decreasing score vs predicted SPL excess.
_PENALTY_K = 0.35
_PENALTY_P = 2.0

_ZONING_MULTIPLIER: dict[ZoningBucket, float] = {
    ZoningBucket.RESIDENTIAL: 1.15,
    ZoningBucket.PUBLIC: 1.05,
    ZoningBucket.COMMERCIAL: 1.0,
    ZoningBucket.INDUSTRIAL: 0.9,
    ZoningBucket.OTHER: 1.0,
}


def zoning_multiplier(bucket: ZoningBucket) -> float:
    return _ZONING_MULTIPLIER.get(bucket, 1.0)


def is_clock_nighttime(hour: int, minute: int = 0) -> bool:
    """Local-time nighttime window per §4.3 sketch (22:00 inclusive through before 07:00)."""
    _ = minute
    return hour >= 22 or hour < 7


def parse_clock_time(clock_time: str) -> tuple[int, int]:
    parts = clock_time.strip().split(":")
    if len(parts) != 2:
        raise ValueError("clock_time must look like HH:MM")
    h, m = int(parts[0]), int(parts[1])
    if not (0 <= h <= 23 and 0 <= m <= 59):
        raise ValueError("clock_time out of range")
    return h, m


def resolve_is_nighttime(
    *,
    explicit: bool | None,
    local_timestamp: datetime | None,
    timezone: str | None,
    clock_time: str | None,
) -> tuple[bool, dict[str, Any]]:
    """
    Resolve nighttime flag.

    Precedence:
    1. ``explicit`` when provided.
    2. Hour inferred from timezone-aware ``local_timestamp``.
    3. ``timezone`` + ``clock_time`` (today's calendar date in that zone).

    Raises ``ValueError`` for incompatible inputs.
    """
    ctx: dict[str, Any] = {"window": NIGHT_WINDOW_LABEL}

    if explicit is not None:
        ctx["is_nighttime"] = explicit
        return explicit, ctx

    if local_timestamp is not None:
        if local_timestamp.tzinfo is None:
            raise ValueError("local_timestamp must be timezone-aware (§4.2)")
        flag = is_clock_nighttime(local_timestamp.hour, local_timestamp.minute)
        ctx["is_nighttime"] = flag
        ctx["source"] = "local_timestamp"
        return flag, ctx

    if timezone is not None and clock_time is not None:
        try:
            tz = ZoneInfo(timezone)
        except ZoneInfoNotFoundError as e:
            raise ValueError(f"Unknown IANA timezone: {timezone}") from e
        h, m = parse_clock_time(clock_time)
        now = datetime.now(tz)
        anchor = datetime(
            now.year,
            now.month,
            now.day,
            h,
            m,
            tzinfo=tz,
        )
        flag = is_clock_nighttime(anchor.hour, anchor.minute)
        ctx["is_nighttime"] = flag
        ctx["source"] = "timezone+clock_time"
        ctx["timezone"] = timezone
        ctx["clock_time"] = clock_time
        return flag, ctx

    if timezone is not None or clock_time is not None:
        raise ValueError("Provide both timezone and clock_time together, or neither.")

    ctx["is_nighttime"] = False
    ctx["source"] = "default_daytime"
    return False, ctx


@dataclass(frozen=True)
class ViabilityScores:
    predicted_db_physical: float
    predicted_db: float
    threshold_db: float
    exceedance_db: float
    night_db_penalty_applied: float
    health_score: int
    risk_band: str


def compute_viability_scores(
    *,
    predicted_db_physical: float,
    is_nighttime: bool,
    threshold_db: float,
    zoning: ZoningBucket,
) -> ViabilityScores:
    """§4.3 penalty curve + risk bands."""
    penalty = NIGHT_DB_PENALTY if is_nighttime else 0.0
    predicted_db = predicted_db_physical + penalty

    exceedance_db = max(0.0, predicted_db - threshold_db)
    mult = zoning_multiplier(zoning)
    penalty_term = _PENALTY_K * (exceedance_db**_PENALTY_P) * mult
    health_score = int(round(max(0.0, min(100.0, 100.0 - penalty_term))))

    risk_band = _risk_band(health_score=health_score, exceedance_db=exceedance_db)

    return ViabilityScores(
        predicted_db_physical=predicted_db_physical,
        predicted_db=predicted_db,
        threshold_db=threshold_db,
        exceedance_db=exceedance_db,
        night_db_penalty_applied=penalty,
        health_score=health_score,
        risk_band=risk_band,
    )


def _risk_band(*, health_score: int, exceedance_db: float) -> str:
    if exceedance_db <= 0.0:
        return "LOW"
    if health_score >= 70:
        return "LOW"
    if health_score >= 40:
        return "MED"
    return "HIGH"


def build_viability_notes(
    *,
    zoning: ZoningBucket,
    is_nighttime: bool,
    night_penalty_applied: float,
) -> list[str]:
    notes: list[str] = []
    if zoning == ZoningBucket.RESIDENTIAL:
        notes.append("Within residential-class OSM land use.")
    elif zoning == ZoningBucket.PUBLIC:
        notes.append("Within public / civic amenity footprint.")
    elif zoning == ZoningBucket.COMMERCIAL:
        notes.append("Within commercial-class OSM land use.")
    elif zoning == ZoningBucket.INDUSTRIAL:
        notes.append("Within industrial-class OSM land use.")
    else:
        notes.append("No classified OSM zoning polygon covers this coordinate.")

    if is_nighttime and night_penalty_applied > 0:
        notes.append(
            f"Nighttime assessment (+{int(night_penalty_applied)} dB applied to predicted_db only)."
        )

    return notes


def viability_payload_dict(
    *,
    lon: float,
    lat: float,
    weighting: AcousticWeighting,
    zoning: ZoningBucket,
    scores: ViabilityScores,
    local_time_context: dict[str, Any],
) -> dict[str, Any]:
    """§4.3 conceptual JSON shape."""
    notes = build_viability_notes(
        zoning=zoning,
        is_nighttime=bool(local_time_context.get("is_nighttime")),
        night_penalty_applied=scores.night_db_penalty_applied,
    )
    return {
        "coord": [lon, lat],
        "predicted_db_physical": scores.predicted_db_physical,
        "predicted_db": scores.predicted_db,
        "weighting": weighting.value,
        "zoning": zoning.value,
        "threshold_db": scores.threshold_db,
        "exceedance_db": scores.exceedance_db,
        "local_time_context": local_time_context,
        "night_db_penalty_applied": scores.night_db_penalty_applied,
        "health_score": scores.health_score,
        "risk_band": scores.risk_band,
        "notes": notes,
    }
