/**
 * Local tangent-plane helpers matching ``backend.physics`` for grid ↔ lon/lat.
 */

export type BBox = {
  min_lon: number
  min_lat: number
  max_lon: number
  max_lat: number
}

const R = 6371000

export function metricExtent(bbox: BBox): {
  width_m: number
  height_m: number
  lon0: number
  lat0: number
} {
  const lon0 = bbox.min_lon
  const lat0 = bbox.min_lat
  const phi0 = (lat0 * Math.PI) / 180
  const width_m =
    ((bbox.max_lon - lon0) * Math.PI) / 180 * R * Math.cos(phi0)
  const height_m = ((bbox.max_lat - lat0) * Math.PI) / 180 * R
  return { width_m, height_m, lon0, lat0 }
}

export function localMetersToLonLat(
  x_m: number,
  y_m: number,
  lon0: number,
  lat0: number,
): [number, number] {
  const phi0 = (lat0 * Math.PI) / 180
  const lon = lon0 + (x_m / (R * Math.cos(phi0))) * (180 / Math.PI)
  const lat = lat0 + (y_m / R) * (180 / Math.PI)
  return [lon, lat]
}

export type NoiseGridPoint = { lon: number; lat: number; db: number }

/** Expand backend ``grid_db[row][col]`` into cell-center samples with ``properties.db`` semantics (§5.1). */
export function gridToNoisePoints(
  bbox: BBox,
  rows: number,
  cols: number,
  gridDb: number[][],
): NoiseGridPoint[] {
  const { width_m, height_m, lon0, lat0 } = metricExtent(bbox)
  const dx = width_m / cols
  const dy = height_m / rows
  const points: NoiseGridPoint[] = []
  for (let i = 0; i < rows; i++) {
    for (let j = 0; j < cols; j++) {
      const x = (j + 0.5) * dx
      const y = (i + 0.5) * dy
      const [lon, lat] = localMetersToLonLat(x, y, lon0, lat0)
      points.push({ lon, lat, db: gridDb[i][j] })
    }
  }
  return points
}

export function bboxCenter(bbox: BBox): { lon: number; lat: number } {
  return {
    lon: (bbox.min_lon + bbox.max_lon) / 2,
    lat: (bbox.min_lat + bbox.max_lat) / 2,
  }
}
