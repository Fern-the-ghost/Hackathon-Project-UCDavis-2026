import { useMemo } from 'react'
import { DeckGL } from '@deck.gl/react'
import { HeatmapLayer } from '@deck.gl/aggregation-layers'
import { Map } from 'react-map-gl/mapbox'
import type { MapViewState } from '@deck.gl/core'
import 'mapbox-gl/dist/mapbox-gl.css'

import {
  DEFAULT_BBOX,
  HEATMAP_COLOR_RANGE,
  HEATMAP_INTENSITY,
  HEATMAP_RADIUS_PIXELS,
  HEATMAP_THRESHOLD,
} from '../config/noiseMap'
import type { NoiseGridPoint } from '../lib/geo'
import { bboxCenter } from '../lib/geo'

type PlanningMapProps = {
  mapboxToken: string
  points: NoiseGridPoint[]
  weightingLabel: string
  loading?: boolean
  errorText?: string | null
}

export function PlanningMap({
  mapboxToken,
  points,
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
      new HeatmapLayer<NoiseGridPoint>({
        id: 'urbanacoustic-noise-heatmap',
        data: points,
        pickable: false,
        radiusPixels: HEATMAP_RADIUS_PIXELS,
        intensity: HEATMAP_INTENSITY,
        threshold: HEATMAP_THRESHOLD,
        colorRange: HEATMAP_COLOR_RANGE,
        getPosition: (d) => [d.lon, d.lat],
        getWeight: (d) => Math.pow(10, d.db / 10),
        aggregation: 'SUM',
        weightsTextureSize: 2048,
      }),
    ],
    [points],
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
          <span className="muted">§5.1 cumulative SPL · {weightingLabel}</span>
        </div>
        {loading ? <div className="status-chip">Loading grid…</div> : null}
        {errorText ? <div className="error-chip">{errorText}</div> : null}
      </div>

      <div className="legend">
        <div className="legend-title">Modeled outdoor level (heatmap)</div>
        <div className="legend-bar" />
        <div className="legend-ticks">
          <span>&lt; 40 dB (quiet)</span>
          <span>&gt; 55 dB (loud)</span>
        </div>
      </div>
    </div>
  )
}
