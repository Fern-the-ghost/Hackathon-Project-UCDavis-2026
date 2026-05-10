import { useMemo } from 'react'
import { DeckGL } from '@deck.gl/react'
import { GeoJsonLayer } from '@deck.gl/layers'
import { Map } from 'react-map-gl/mapbox'
import type { MapViewState } from '@deck.gl/core'
import 'mapbox-gl/dist/mapbox-gl.css'

import {
  DEFAULT_BBOX,
  HEATMAP_COLOR_RANGE,
} from '../config/noiseMap'
import { bboxCenter } from '../lib/geo'

type PlanningMapProps = {
  mapboxToken: string
  noisePolygons: GeoJSON.FeatureCollection
  conflictMask: GeoJSON.FeatureCollection | null
  weightingLabel: string
  loading?: boolean
  errorText?: string | null
}

/** §5.1 / §5.2 dB → RGBA color ramp.
 *
 *  ≤40 dB → transparent [0,0,0,0]
 *  40-45 dB → green
 *  45-50 dB → yellow
 *  50-55 dB → orange
 *  ≥55 dB → red
 *
 *  Linear interpolation between stops for smooth transitions. */
function dbColor(db: number): [number, number, number, number] {
  const stops: [number, [number, number, number, number]][] = [
    [40, HEATMAP_COLOR_RANGE[1]],   // green
    [45, HEATMAP_COLOR_RANGE[2]],   // yellow
    [50, HEATMAP_COLOR_RANGE[3]],   // orange
    [55, HEATMAP_COLOR_RANGE[4]],   // red
  ]

  if (db <= 40) return [0, 0, 0, 0]
  if (db >= 55) return stops[3][1]

  for (let i = 0; i < stops.length - 1; i++) {
    const [t0, c0] = stops[i]
    const [t1, c1] = stops[i + 1]
    if (db >= t0 && db <= t1) {
      const f = (db - t0) / (t1 - t0)
      return [
        Math.round(c0[0] + (c1[0] - c0[0]) * f),
        Math.round(c0[1] + (c1[1] - c0[1]) * f),
        Math.round(c0[2] + (c1[2] - c0[2]) * f),
        Math.round(c0[3] + (c1[3] - c0[3]) * f),
      ]
    }
  }
  return stops[3][1]
}

export function PlanningMap({
  mapboxToken,
  noisePolygons,
  conflictMask,
  weightingLabel,
  loading,
  errorText,
}: PlanningMapProps) {
  const initialViewState: MapViewState = useMemo(() => {
    const c = bboxCenter(DEFAULT_BBOX)
    return {
      longitude: c.lon,
      latitude: c.lat,
      zoom: 11.6,
      pitch: 0,
      bearing: 0,
    }
  }, [])

  const layers = useMemo(
    () => [
      // §5.1 Noise grid — semi-transparent data layer showing streets through the grid.
      new GeoJsonLayer({
        id: 'urbanacoustic-noise-grid',
        data: noisePolygons,
        filled: true,
        opacity: 0.6,
        getFillColor: (f: GeoJSON.Feature) =>
          dbColor((f.properties as { db?: number })?.db ?? 0),
        stroked: false,
        pickable: false,
      }),

      // §5.2 Conflict mask — bold red fill + dark red stroke to pop as specific alerts.
      new GeoJsonLayer({
        id: 'urbanacoustic-conflict-mask',
        data: conflictMask ?? { type: 'FeatureCollection', features: [] },
        filled: true,
        getFillColor: [220, 38, 38, 180],
        getLineColor: [180, 20, 20, 230],
        lineWidthUnits: 'pixels',
        lineWidthMinPixels: 2,
        stroked: true,
        opacity: 0.7,
        pickable: false,
      }),
    ],
    [noisePolygons, conflictMask],
  )

  return (
    <div className="planning-map-root">
      <DeckGL
        initialViewState={initialViewState}
        controller
        layers={layers}
        style={{ width: '100%', height: '100%' }}
      >
        <Map
          mapboxAccessToken={mapboxToken}
          mapStyle="mapbox://styles/mapbox/light-v11"
          reuseMaps
        />
      </DeckGL>

      <div className="map-overlay-top">
        <div className="title-chip">
          <strong>UrbanAcoustic</strong>
          <span className="muted">§5.1 noise grid · {weightingLabel}</span>
        </div>
        {loading ? <div className="status-chip">Loading grid…</div> : null}
        {errorText ? <div className="error-chip">{errorText}</div> : null}
      </div>

      <div className="legend">
        <div className="legend-title">Modeled outdoor level (dB)</div>
        <div className="legend-bar" />
        <div className="legend-ticks">
          <span>{'<'} 40 dB (quiet)</span>
          <span>{'>'} 55 dB (loud)</span>
        </div>
      </div>
    </div>
  )
}