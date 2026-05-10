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

/** §5.1 Zoom-stable noise field: GeoJSON FeatureCollection of cell-aligned polygons.
 *
 * Each cell is a world-space polygon (GridSpec cell size), so coverage is
 * physically anchored and identical at every zoom level — unlike a
 * pixel-radius HeatmapLayer which shrinks/grows with the viewport.
 *
 * Cells are inset by GAP_FRACTION on each side to produce a subtle "mesh"
 * gap between adjacent squares for a high-end engineering look. */
const GAP_FRACTION = 0.03  // 3% inset per side = visible gap without breaking continuity

export function gridToNoisePolygons(
  bbox: BBox,
  rows: number,
  cols: number,
  gridDb: number[][],
  zoningMask?: string[][],
): GeoJSON.FeatureCollection {
  const { width_m, height_m, lon0, lat0 } = metricExtent(bbox)
  const dx = width_m / cols
  const dy = height_m / rows

  const features: GeoJSON.Feature[] = []

  for (let i = 0; i < rows; i++) {
    for (let j = 0; j < cols; j++) {
      const db = gridDb[i]?.[j]
      if (db == null) continue

      // Inset each cell by GAP_FRACTION to create the mesh look
      const inset = GAP_FRACTION
      const x0 = (j + inset) * dx
      const y0 = (i + inset) * dy
      const x1 = (j + 1 - inset) * dx
      const y1 = (i + 1 - inset) * dy

      const [lon0_cc, lat0_cc] = localMetersToLonLat(x0, y0, lon0, lat0)
      const [lon1_cc, lat1_cc] = localMetersToLonLat(x1, y0, lon0, lat0)
      const [lon2_cc, lat2_cc] = localMetersToLonLat(x1, y1, lon0, lat0)
      const [lon3_cc, lat3_cc] = localMetersToLonLat(x0, y1, lon0, lat0)

      const zone = zoningMask?.[i]?.[j] ?? 'Unknown'
      features.push({
        type: 'Feature',
        properties: { db, zone },
        geometry: {
          type: 'Polygon',
          coordinates: [[
            [lon0_cc, lat0_cc],
            [lon1_cc, lat1_cc],
            [lon2_cc, lat2_cc],
            [lon3_cc, lat3_cc],
            [lon0_cc, lat0_cc],
          ]],
        },
      })
    }
  }

  return { type: 'FeatureCollection', features }
}

export function bboxCenter(bbox: BBox): { lon: number; lat: number } {
  return {
    lon: (bbox.min_lon + bbox.max_lon) / 2,
    lat: (bbox.min_lat + bbox.max_lat) / 2,
  }
}

/** §5.2 Conflict mask: GeoJSON FeatureCollection of residential cells exceeding threshold dB.
 *
 * Each conflict cell becomes a polygon aligned to the metric grid with a small
 * inset gap for the mesh look, then projected back to WGS84.
 * Gets a bold red stroke in the layer config for visual pop. */
export function gridToConflictMask(
  bbox: BBox,
  rows: number,
  cols: number,
  cellSizeM: number,
  gridDb: number[][],
  zoningMask: string[][],
  thresholdDb: number,
): GeoJSON.FeatureCollection {
  const { width_m, height_m, lon0, lat0 } = metricExtent(bbox)
  const dx = width_m / cols
  const dy = height_m / rows

  const features: GeoJSON.Feature[] = []

  for (let i = 0; i < rows; i++) {
    for (let j = 0; j < cols; j++) {
      const isResidential = zoningMask[i]?.[j] === 'RESIDENTIAL'
      const db = gridDb[i]?.[j]
      if (!isResidential || db == null || db <= thresholdDb) continue

      // Inset by same GAP_FRACTION so conflict cells align with noise grid mesh
      const inset = GAP_FRACTION
      const x0 = (j + inset) * dx
      const y0 = (i + inset) * dy
      const x1 = (j + 1 - inset) * dx
      const y1 = (i + 1 - inset) * dy

      const [lon0_cc, lat0_cc] = localMetersToLonLat(x0, y0, lon0, lat0)
      const [lon1_cc, lat1_cc] = localMetersToLonLat(x1, y0, lon0, lat0)
      const [lon2_cc, lat2_cc] = localMetersToLonLat(x1, y1, lon0, lat0)
      const [lon3_cc, lat3_cc] = localMetersToLonLat(x0, y1, lon0, lat0)

      features.push({
        type: 'Feature',
        properties: { db },
        geometry: {
          type: 'Polygon',
          coordinates: [
            [
              [lon0_cc, lat0_cc],
              [lon1_cc, lat1_cc],
              [lon2_cc, lat2_cc],
              [lon3_cc, lat3_cc],
              [lon0_cc, lat0_cc],
            ],
          ],
        },
      })
    }
  }

  return { type: 'FeatureCollection', features }
}
