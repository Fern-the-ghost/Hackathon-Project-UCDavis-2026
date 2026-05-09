"""FastAPI entry: Phase A grid calculation."""

from __future__ import annotations

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field, model_validator

from backend.physics import (
    AcousticWeighting,
    NoiseSourceInput,
    compute_grid_levels_db,
)

app = FastAPI(title="UrbanAcoustic", version="0.1.0")


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
        description="Metadata only in Phase A; does not change physics.",
    )


class CalculateRequest(BaseModel):
    bbox: BoundingBox
    sources: list[NoiseSourcePayload] = Field(..., min_length=1)
    weighting: AcousticWeighting = AcousticWeighting.DBA
    cell_size_m: float = Field(50.0, gt=0, description="Approximate cell edge (meters)")
    A_abs: float = Field(
        0.0,
        ge=0.0,
        description="Nominal urban absorption term §3.2 (dB); dBC uses half.",
    )


class CalculateResponse(BaseModel):
    rows: int
    cols: int
    cell_size_m: float
    weighting: str
    A_abs: float
    grid_db: list[list[float]]


@app.post("/calculate", response_model=CalculateResponse)
def calculate(body: CalculateRequest) -> CalculateResponse:
    """Return cumulative SPL grid (§3.4) over bbox for given sources."""
    try:
        sources = [
            NoiseSourceInput(
                lon=s.lon,
                lat=s.lat,
                reference_level_db=s.reference_level_db,
            )
            for s in body.sources
        ]
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
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    grid_list = L_grid.tolist()
    n_rows, n_cols = L_grid.shape
    return CalculateResponse(
        rows=n_rows,
        cols=n_cols,
        cell_size_m=body.cell_size_m,
        weighting=body.weighting.value,
        A_abs=body.A_abs,
        grid_db=grid_list,
    )


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
