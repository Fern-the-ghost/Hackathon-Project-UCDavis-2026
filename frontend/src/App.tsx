import { useEffect, useMemo, useState } from 'react'

import { PlanningMap } from './components/PlanningMap'
import {
  DEFAULT_BBOX,
  DEFAULT_SOURCES,
} from './config/noiseMap'
import { postCalculate } from './lib/api'
import { bboxCenter, gridToConflictMask, gridToNoisePolygons } from './lib/geo'

import './App.css'

const MAPBOX_TOKEN = import.meta.env.VITE_MAPBOX_ACCESS_TOKEN ?? ''
const API_BASE =
  import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

const POPULATION_PER_CELL = 2.5
const CONFLICT_THRESHOLD_DB = 45

function App() {
  const [noisePolygons, setNoisePolygons] = useState<GeoJSON.FeatureCollection>(() => ({
    type: 'FeatureCollection',
    features: [],
  }))
  const [conflictMask, setConflictMask] = useState<GeoJSON.FeatureCollection | null>(null)
  const [conflictStats, setConflictStats] = useState({ cellCount: 0, areaHa: 0, population: 0 })
  const [weighting, setWeighting] = useState<'DBA' | 'DBC'>('DBA')
  const [loading, setLoading] = useState(true)
  const [errorText, setErrorText] = useState<string | null>(null)

  const cellSizeM = 85

  const requestBody = useMemo(
    () => ({
      bbox: DEFAULT_BBOX,
      sources: DEFAULT_SOURCES.map((s) => ({ ...s })),
      weighting,
      cell_size_m: cellSizeM,
      A_abs: 8.0,
    }),
    [weighting],
  )

  useEffect(() => {
    let cancelled = false
    async function load() {
      setLoading(true)
      setErrorText(null)
      try {
        const data = await postCalculate(API_BASE, requestBody)
        if (cancelled) return
        const polys = gridToNoisePolygons(
          DEFAULT_BBOX,
          data.rows,
          data.cols,
          data.grid_db,
        )
        setNoisePolygons(polys)

        const mask = gridToConflictMask(
          DEFAULT_BBOX,
          data.rows,
          data.cols,
          data.cell_size_m,
          data.grid_db,
          data.zoning_mask,
          CONFLICT_THRESHOLD_DB,
        )
        setConflictMask(mask)

        const cellCount = mask.features.length
        const areaHa = (cellCount * data.cell_size_m * data.cell_size_m) / 10000
        const population = Math.round(cellCount * POPULATION_PER_CELL)
        setConflictStats({ cellCount, areaHa, population })
      } catch (err) {
        if (!cancelled) {
          setErrorText(err instanceof Error ? err.message : String(err))
        }
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    void load()
    return () => {
      cancelled = true
    }
  }, [requestBody])

  if (!MAPBOX_TOKEN.trim()) {
    return (
      <div className="startup-error">
        <h1>Mapbox token missing</h1>
        <p>
          Create <code>frontend/.env</code> with{' '}
          <code>VITE_MAPBOX_ACCESS_TOKEN</code> set to a Mapbox public token, then
          restart <code>npm run dev</code>.
        </p>
        <p className="muted">
          Backend URL defaults to <code>http://localhost:8000</code> (
          <code>VITE_API_BASE_URL</code>).
        </p>
      </div>
    )
  }

  return (
    <div className="app-shell">
      <PlanningMap
        mapboxToken={MAPBOX_TOKEN}
        noisePolygons={noisePolygons}
        conflictMask={conflictMask}
        conflictStats={conflictStats}
        weightingLabel={weighting}
        loading={loading}
        errorText={errorText}
      />

      <aside className="controls-rail">
        <div className="panel">
          <div className="panel-title">Acoustic weighting</div>
          <div className="toggle-row">
            <button
              type="button"
              className={weighting === 'DBA' ? 'active' : ''}
              onClick={() => setWeighting('DBA')}
            >
              dBA
            </button>
            <button
              type="button"
              className={weighting === 'DBC' ? 'active' : ''}
              onClick={() => setWeighting('DBC')}
            >
              dBC
            </button>
          </div>
          <p className="muted small">
            <strong>{weighting}</strong> · {weighting === 'DBA' ? 'Standard human hearing curve; effective absorption at 100%.' : 'Low-frequency emphasis; absorption halved — hum carries farther.'}
          </p>
        </div>

        <div className="panel impact-summary" style={{ marginTop: 12 }}>
          <div className="panel-title">Impact summary</div>
          {conflictStats.cellCount > 0 ? (
            <>
              <div className="metric-row">
                <span className="metric-label">Conflict area</span>
                <span className="metric-value">{conflictStats.areaHa.toFixed(1)} ha</span>
              </div>
              <div className="metric-row">
                <span className="metric-label">Affected residents (est.)</span>
                <span className="metric-value">~{conflictStats.population}</span>
              </div>
              <div className="metric-row">
                <span className="metric-label">Conflict cells</span>
                <span className="metric-value">{conflictStats.cellCount}</span>
              </div>
            </>
          ) : (
            <p className="muted small">No residential conflicts above {CONFLICT_THRESHOLD_DB} dB.</p>
          )}
        </div>
      </aside>
    </div>
  )
}

export default App
