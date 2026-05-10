"""FastAPI entry: Phase A grid calculation + Phase B OSM zoning & viability."""

from __future__ import annotations

from datetime import datetime
from enum import Enum

import httpx
import numpy as np
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator, model_validator

from backend.physics import (
    AcousticWeighting,
    NoiseSourceInput,
    bilinear_sample_db,
    compute_grid_levels_db,
    compute_metric_layout,
    local_meters_to_lonlat,
    lonlat_to_metric_offset,
)
from backend.services.osm_service import OSMBoundingBox, fetch_zoning_features
from backend.services.zoning_mapper import (
    ZoningBucket,
    bucket_polygons,
    classify_lonlat,
    merge_bucket_geometries,
    rasterize_zoning_buckets,
)
from backend.viability import (
    compute_viability_scores,
    resolve_is_nighttime,
    viability_payload_dict,
)

app = FastAPI(title="UrbanAcoustic", version="0.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:4173",
        "http://127.0.0.1:4173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class BoundingBox(BaseModel):
    min_lon: float = Field(..., description="Western edge (degrees)")
    min_lat: float = Field(..., description="Southern edge (degrees)")
    max_lon: float = Field(..., description="Eastern edge (degrees)")
    max_lat: float = Field(..., description="Northern edge (degrees)")

    @model_validator(mode="after")
    def check_extent(self) -> BoundingBox:
        if self.max_lon <= self.min_lon or self.max_lat <= self.min_lat:
            raise ValueError("bbox requires max_lon > min_lon and max_lat > min_lat")
        return self


class NoiseSourcePayload(BaseModel):
    id: str | None = None
    lon: float
    lat: float
    reference_level_db: float
    cooling_mw: float | None = Field(
        default=None,
        description="Metadata only unless mapped to SPL elsewhere.",
    )


class BarrierType(str, Enum):
    CONCRETE = "concrete"
    GREEN = "green"


class BarrierPolygon(BaseModel):
    """A barrier footprint: outer ring as list of [lon, lat] pairs (§3.5)."""
    ring: list[list[float]] = Field(..., min_length=3)
    type: BarrierType = BarrierType.CONCRETE


class CalculateRequest(BaseModel):
    bbox: BoundingBox
    sources: list[NoiseSourcePayload] = Field(..., min_length=1)
    weighting: AcousticWeighting = AcousticWeighting.DBA
    cell_size_m: float = Field(
        85.0,
        gt=0,
        description="Approximate cell edge (meters). Capped so grid ≤ 60×60 for demo performance.",
    )
    A_abs: float = Field(
        0.0,
        ge=0.0,
        description="Nominal urban absorption term §3.2 (dB); dBC uses half.",
    )
    barriers: list[BarrierPolygon] = Field(
        default_factory=list,
        description="§3.5 barrier footprints (WGS84 rings) for ray-intersection shadow.",
    )


class CalculateResponse(BaseModel):
    rows: int
    cols: int
    cell_size_m: float
    weighting: str
    A_abs: float
    grid_db: list[list[float]]
    zoning_mask: list[list[str]]
    barriers_applied: int


class ViabilityRequest(BaseModel):
    """§4.2 viability assessment inputs."""

    coord: tuple[float, float] = Field(
        ...,
        description="(lon, lat) WGS84 degrees — ordering matches Mapbox-style GeoJSON.",
    )
    bbox: BoundingBox
    sources: list[NoiseSourcePayload] = Field(..., min_length=1)
    weighting: AcousticWeighting = AcousticWeighting.DBA
    cell_size_m: float = Field(50.0, gt=0)
    A_abs: float = Field(0.0, ge=0.0)
    threshold_db: float = Field(45.0, ge=0.0, description="Sleep-health guideline ceiling (§4).")
    is_nighttime: bool | None = Field(
        default=None,
        description="Explicit override for §4.3 nighttime +10 dB adjustment.",
    )
    local_timestamp: datetime | None = Field(
        default=None,
        description="Timezone-aware ISO-8601 instant for deriving nighttime.",
    )
    timezone: str | None = Field(default=None, description="IANA timezone name.")
    clock_time: str | None = Field(
        default=None,
        description='Local wall-clock "HH:MM" interpreted in ``timezone``.',
    )

    @field_validator("local_timestamp")
    @classmethod
    def timestamp_tz(cls, v: datetime | None) -> datetime | None:
        if v is None:
            return v
        if v.tzinfo is None:
            raise ValueError("local_timestamp must include tzinfo (timezone-aware).")
        return v


class ViabilityResponse(BaseModel):
    coord: list[float]
    predicted_db_physical: float
    predicted_db: float
    weighting: str
    zoning: str
    threshold_db: float
    exceedance_db: float
    local_time_context: dict
    night_db_penalty_applied: float
    health_score: int
    risk_band: str
    notes: list[str]


def _noise_sources(payloads: list[NoiseSourcePayload]) -> list[NoiseSourceInput]:
    return [
        NoiseSourceInput(
            lon=s.lon,
            lat=s.lat,
            reference_level_db=s.reference_level_db,
        )
        for s in payloads
    ]


def _build_zoning_mask(
    *,
    lon0: float,
    lat0: float,
    xs_half: np.ndarray,
    ys_half: np.ndarray,
    merged_zoning: dict,
) -> np.ndarray:
    CX, CY = np.meshgrid(xs_half, ys_half)
    lon_cc, lat_cc = local_meters_to_lonlat(CX, CY, lon0, lat0)
    return rasterize_zoning_buckets(lon_cc, lat_cc, merged_zoning)


@app.post("/calculate", response_model=CalculateResponse)
def calculate(body: CalculateRequest) -> CalculateResponse:
    """Return cumulative SPL grid (§3.4) plus §6 zoning mask."""
    try:
        sources = _noise_sources(body.sources)

        # Step 1: Build metric layout axes (needed before both zoning and grid)
        # Cap resolution at 60×60 for snappy demo performance
        effective_cell_size = body.cell_size_m
        width_m, height_m, grid_rows, grid_cols, xs_half, ys_half = compute_metric_layout(
            body.bbox.min_lon,
            body.bbox.min_lat,
            body.bbox.max_lon,
            body.bbox.max_lat,
            effective_cell_size,
        )
        if grid_rows > 60 or grid_cols > 60:
            ratio = max(grid_rows / 60, grid_cols / 60)
            effective_cell_size = effective_cell_size * ratio
            width_m, height_m, grid_rows, grid_cols, xs_half, ys_half = compute_metric_layout(
                body.bbox.min_lon,
                body.bbox.min_lat,
                body.bbox.max_lon,
                body.bbox.max_lat,
                effective_cell_size,
            )

        # Step 2: Fetch OSM zoning and rasterize it to a numpy array (before grid)
        osm_bbox = OSMBoundingBox.model_validate(body.bbox.model_dump())
        try:
            feats = fetch_zoning_features(osm_bbox)
            grouped = bucket_polygons(feats)
            merged = merge_bucket_geometries(grouped)
        except (httpx.HTTPError, Exception) as exc:
            import logging
            logging.getLogger("urbanacoustic").warning(
                "OSM fetch failed: %s", exc
            )
            merged = {}

        zoning_arr_np: np.ndarray | None = None
        try:
            if merged:
                zoning_arr_np = _build_zoning_mask(
                    lon0=body.bbox.min_lon,
                    lat0=body.bbox.min_lat,
                    xs_half=xs_half,
                    ys_half=ys_half,
                    merged_zoning=merged,
                )
        except Exception as exc:
            import logging
            logging.getLogger("urbanacoustic").warning(
                "Zoning rasterization failed: %s", exc
            )

        # Step 3: Compute noise grid WITH barrier shadows (zoning mask available)
        barrier_rings = [b.ring for b in body.barriers]
        barrier_types = [b.type.value for b in body.barriers]
        L_grid, xs_half, ys_half = compute_grid_levels_db(
            body.bbox.min_lon,
            body.bbox.min_lat,
            body.bbox.max_lon,
            body.bbox.max_lat,
            effective_cell_size,
            sources,
            body.weighting,
            A_abs=body.A_abs,
            barriers=barrier_rings if barrier_rings else None,
            barrier_types=barrier_types if barrier_rings else None,
            zoning_mask=zoning_arr_np,
        )
        n_rows, n_cols = L_grid.shape

        # Step 4: Build zoning_mask list for response
        if zoning_arr_np is not None:
            zoning_mask = [
                [str(zoning_arr_np[i, j]) for j in range(zoning_arr_np.shape[1])]
                for i in range(zoning_arr_np.shape[0])
            ]
        else:
            zoning_mask = [
                [str(ZoningBucket.OTHER.value)] * n_cols for _ in range(n_rows)
            ]
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    # If zoning_mask was built inline, we still need it; if it's a placeholder from the
    # else/except above it's already set. Now ensure it exists after the conditional block.
    grid_list = L_grid.tolist()
    return CalculateResponse(
        rows=n_rows,
        cols=n_cols,
        cell_size_m=body.cell_size_m,
        weighting=body.weighting.value,
        A_abs=body.A_abs,
        grid_db=grid_list,
        zoning_mask=zoning_mask,
        barriers_applied=len(barrier_rings),
    )


@app.post("/analyze/viability", response_model=ViabilityResponse)
def analyze_viability(body: ViabilityRequest) -> ViabilityResponse:
    """§4 ``assess_development_viability`` — SPL sample + OSM zoning + nighttime adjustment."""
    lon, lat = body.coord

    if not (
        body.bbox.min_lon <= lon <= body.bbox.max_lon
        and body.bbox.min_lat <= lat <= body.bbox.max_lat
    ):
        raise HTTPException(status_code=400, detail="coord must lie inside bbox.")

    try:
        night_flag, ctx = resolve_is_nighttime(
            explicit=body.is_nighttime,
            local_timestamp=body.local_timestamp,
            timezone=body.timezone,
            clock_time=body.clock_time,
        )

        sources = _noise_sources(body.sources)
        L_grid, _, _ = compute_grid_levels_db(
            body.bbox.min_lon,
            body.bbox.min_lat,
            body.bbox.max_lon,
            body.bbox.max_lat,
            body.cell_size_m,
            sources,
            body.weighting,
            A_abs=body.A_abs,
        )
        width_m, height_m, _, _, _, _ = compute_metric_layout(
            body.bbox.min_lon,
            body.bbox.min_lat,
            body.bbox.max_lon,
            body.bbox.max_lat,
            body.cell_size_m,
        )
        x_m, y_m = lonlat_to_metric_offset(lon, lat, body.bbox.min_lon, body.bbox.min_lat)
        L_phys = bilinear_sample_db(L_grid, x_m, y_m, width_m, height_m)

        osm_bbox = OSMBoundingBox.model_validate(body.bbox.model_dump())
        try:
            feats = fetch_zoning_features(osm_bbox)
        except httpx.HTTPError as exc:
            raise HTTPException(
                status_code=504,
                detail=f"OSM Overpass request failed: {exc}",
            ) from exc

        merged = merge_bucket_geometries(bucket_polygons(feats))
        zoning = classify_lonlat(lon, lat, merged)

        scores = compute_viability_scores(
            predicted_db_physical=L_phys,
            is_nighttime=night_flag,
            threshold_db=body.threshold_db,
            zoning=zoning,
        )
        payload = viability_payload_dict(
            lon=lon,
            lat=lat,
            weighting=body.weighting,
            zoning=zoning,
            scores=scores,
            local_time_context=ctx,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    return ViabilityResponse(**payload)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
