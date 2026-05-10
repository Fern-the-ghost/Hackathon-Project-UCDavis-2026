import { useMemo, useCallback, useState } from 'react'
import { DeckGL } from '@deck.gl/react'
import { GeoJsonLayer } from '@deck.gl/layers'
import { Map } from 'react-map-gl/mapbox'
import type { MapViewState, PickingInfo } from '@deck.gl/core'
import 'mapbox-gl/dist/mapbox-gl.css'

import {
  DEFAULT_BBOX,
  HEATMAP_COLOR_RANGE,
} from '../config/noiseMap'
import type { BarrierRing } from '../lib/api'
import { bboxCenter } from '../lib/geo'

type ConflictStats = {
  cellCount: number
  areaHa: number
  population: number
}

type PlanningMapProps = {
  mapboxToken: string
  noisePolygons: GeoJSON.FeatureCollection
  conflictMask: GeoJSON.FeatureCollection | null
  conflictStats: ConflictStats
  weightingLabel: string
  loading?: boolean
  errorText?: string | null
  barriers: BarrierRing[]
  drawingMode: boolean
  drawPoints: [number, number][]
  onMapClick: (lonlat: [number, number]) => void
  toastMessage?: string | null
}

/** §5.1 / §5.2 dB → RGBA color ramp. */
function dbColor(db: number): [number, number, number, number] {
  const stops: [number, [number, number, number, number]][] = [
    [40, HEATMAP_COLOR_RANGE[1]],
    [45, HEATMAP_COLOR_RANGE[2]],
    [50, HEATMAP_COLOR_RANGE[3]],
    [55, HEATMAP_COLOR_RANGE[4]],
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

/** Convert barrier rings to GeoJSON polygons for display, preserving type in properties. */
function barriersToGeoJSON(barriers: BarrierRing[]): GeoJSON.FeatureCollection {
  return {
    type: 'FeatureCollection',
    features: barriers.map((b) => ({
      type: 'Feature',
      properties: { type: b.type ?? 'concrete' },
      geometry: {
        type: 'Polygon',
        coordinates: [b.ring],
      },
    })),
  }
}

/** Build a draw-preview polygon from two corner clicks. */
function drawPointsToGeoJSON(points: [number, number][]): GeoJSON.FeatureCollection {
  if (points.length < 1) return { type: 'FeatureCollection', features: [] }
  if (points.length === 1) {
    // Single point: show as a small dot
    return {
      type: 'FeatureCollection',
      features: [{
        type: 'Feature',
        properties: {},
        geometry: { type: 'Point', coordinates: points[0] },
      }],
    }
  }
  // Two points: show the diagonal preview
  const [p0, p1] = points
  const ring: number[][] = [
    [p0[0], p0[1]],
    [p1[0], p0[1]],
    [p1[0], p1[1]],
    [p0[0], p1[1]],
    [p0[0], p0[1]],
  ]
  return {
    type: 'FeatureCollection',
    features: [{
      type: 'Feature',
      properties: {},
      geometry: { type: 'Polygon', coordinates: [ring] },
    }],
  }
}

/** Risk descriptor based on dB level. */
function riskDescriptor(db: number): string {
  if (db < 45) return 'Safe'
  if (db < 55) return 'Moderate'
  if (db < 65) return 'High Risk'
  return 'Violation'
}

/** Friendly zoning label. */
function zoneLabel(zone: string): string {
  switch (zone) {
    case 'RESIDENTIAL': return 'Residential'
    case 'COMMERCIAL': return 'Commercial'
    case 'INDUSTRIAL': return 'Industrial'
    default: return 'Other'
  }
}

export function PlanningMap({
  mapboxToken,
  noisePolygons,
  conflictMask,
  conflictStats,
  weightingLabel,
  loading,
  errorText,
  barriers,
  drawingMode,
  drawPoints,
  onMapClick,
  toastMessage,
}: PlanningMapProps) {
  const [tooltip, setTooltip] = useState<{ x: number; y: number; text: string } | null>(null)

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

  const barrierFeatures = useMemo(() => barriersToGeoJSON(barriers), [barriers])
  const drawPreview = useMemo(() => drawPointsToGeoJSON(drawPoints), [drawPoints])

  const handleClick = useCallback((info: PickingInfo) => {
    if (!drawingMode || !info.coordinate) return
    const [lng, lat] = info.coordinate as [number, number]
    onMapClick([lng, lat])
  }, [drawingMode, onMapClick])

  const handleHover = useCallback((info: PickingInfo) => {
    if (info.picked && info.object) {
      const props = (info.object as GeoJSON.Feature).properties as Record<string, unknown> | null
      const db = props?.db as number | undefined
      const zone = props?.zone as string | undefined
      if (db !== undefined && info.x !== undefined && info.y !== undefined) {
        const desc = riskDescriptor(db)
        const zl = zone ? zoneLabel(zone) : ''
        setTooltip({
          x: info.x,
          y: info.y,
          text: `Noise Level: ${db.toFixed(1)} dB · ${desc}${zl ? ` · Zone: ${zl}` : ''}`,
        })
        return
      }
    }
    setTooltip(null)
  }, [])

  const layers = useMemo(
    () => [
      // §5.1 Noise grid — pickable for tooltip
      new GeoJsonLayer({
        id: 'urbanacoustic-noise-grid',
        data: noisePolygons,
        filled: true,
        opacity: 0.7,
        getFillColor: (f: GeoJSON.Feature) =>
          dbColor((f.properties as { db?: number })?.db ?? 0),
        stroked: false,
        pickable: true,
        onHover: handleHover,
      }),

      // §5.2 Conflict mask — pulsing red squares
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

      // §3.5 Barrier footprints — teal for concrete, forest green for green walls
      new GeoJsonLayer({
        id: 'urbanacoustic-barriers',
        data: barrierFeatures,
        filled: true,
        getFillColor: (f: GeoJSON.Feature) => {
          const t = (f.properties as { type?: string })?.type
          return t === 'green'
            ? [22, 163, 74, 200]   // forest green, high opacity
            : [20, 184, 166, 120]  // teal
        },
        getLineColor: (f: GeoJSON.Feature) => {
          const t = (f.properties as { type?: string })?.type
          return t === 'green'
            ? [5, 100, 40, 230]    // dark green stroke
            : [13, 148, 136, 230]  // dark teal stroke
        },
        lineWidthUnits: 'pixels',
        lineWidthMinPixels: 2,
        stroked: true,
        pickable: false,
      }),

      // Draw preview line/polygon
      new GeoJsonLayer({
        id: 'urbanacoustic-draw-preview',
        data: drawPreview,
        filled: true,
        getFillColor: [20, 184, 166, 80],
        getLineColor: [13, 148, 136, 200],
        lineWidthUnits: 'pixels',
        lineWidthMinPixels: 1,
        stroked: true,
        pickable: false,
      }),
    ],
    [noisePolygons, conflictMask, barrierFeatures, drawPreview, handleHover],
  )

  return (
    <div className="planning-map-root">
      <DeckGL
        initialViewState={initialViewState}
        controller
        layers={layers}
        style={{ width: '100%', height: '100%' }}
        onClick={handleClick}
      >
        <Map
          mapboxAccessToken={mapboxToken}
          mapStyle="mapbox://styles/mapbox/dark-v11"
          reuseMaps
          cursor={drawingMode ? 'crosshair' : undefined}
        />
      </DeckGL>

      {/* Loading overlay */}
      {loading && (
        <div className="loading-overlay">
          <div className="loading-spinner" />
          <span className="loading-text">Simulating Acoustic Propagation...</span>
        </div>
      )}

      {/* Tooltip */}
      {tooltip && (
        <div
          className="tooltip-popup"
          style={{
            left: tooltip.x + 12,
            top: tooltip.y - 10,
          }}
        >
          {tooltip.text}
        </div>
      )}

      <div className="map-overlay-top">
        <div className="title-chip">
          <strong>UrbanAcoustic</strong>
          <span className="muted">§5.1 noise grid · {weightingLabel}</span>
        </div>
        {errorText ? <div className="error-chip">{errorText}</div> : null}
        {toastMessage ? <div className="toast-chip">{toastMessage}</div> : null}
      </div>

      <div className="legend">
        <div className="legend-title">Modeled outdoor level (dB)</div>
        <div className="legend-bar" />
        <div className="legend-ticks">
          <span>{'<'} 40 dB (quiet)</span>
          <span>{'>'} 55 dB (loud)</span>
        </div>

        {conflictStats.cellCount > 0 ? (
          <>
            <hr className="legend-divider" />
            <div className="legend-conflict">
              <span className="conflict-swatch pulse-swatch" />
              <span className="muted small">Residential {'>'} 45 dB (Violation Area)</span>
            </div>
          </>
        ) : null}

        {barriers.length > 0 ? (
          <>
            <hr className="legend-divider" />
            <div className="legend-conflict">
              <span className="barrier-swatch" />
              <span className="muted small">Concrete barrier ({barriers.filter(b => b.type !== 'green').length})</span>
            </div>
            <div className="legend-conflict">
              <span className="green-swatch" />
              <span className="muted small">Green wall ({barriers.filter(b => b.type === 'green').length})</span>
            </div>
          </>
        ) : null}
      </div>
    </div>
  )
}