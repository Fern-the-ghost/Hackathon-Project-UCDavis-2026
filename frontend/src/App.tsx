import { useEffect, useMemo, useState } from 'react'

import { PlanningMap } from './components/PlanningMap'
import {
  DEFAULT_BBOX,
  DEFAULT_SOURCES,
} from './config/noiseMap'
import { postCalculate } from './lib/api'
import { bboxCenter, gridToNoisePoints } from './lib/geo'
import type { NoiseGridPoint } from './lib/geo'

import './App.css'

const MAPBOX_TOKEN = import.meta.env.VITE_MAPBOX_ACCESS_TOKEN ?? ''
const API_BASE =
  import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

function App() {
  const [points, setPoints] = useState<NoiseGridPoint[]>(() => {
    const c = bboxCenter(DEFAULT_BBOX)
    return [{ lon: c.lon, lat: c.lat, db: 35 }]
  })
  const [weighting, setWeighting] = useState<'DBA' | 'DBC'>('DBA')
  const [loading, setLoading] = useState(true)
  const [errorText, setErrorText] = useState<string | null>(null)

  const requestBody = useMemo(
    () => ({
      bbox: DEFAULT_BBOX,
      sources: DEFAULT_SOURCES.map((s) => ({ ...s })),
      weighting,
      cell_size_m: 85,
      A_abs: 2.0,
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
        const next = gridToNoisePoints(
          DEFAULT_BBOX,
          data.rows,
          data.cols,
          data.grid_db,
        )
        setPoints(next)
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
        points={points}
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
            Heatmap uses linear intensity{' '}
            <code>10^(dB/10)</code> per §5.1 so overlaps behave like incoherent
            energy density.
          </p>
        </div>
      </aside>
    </div>
  )
}

export default App
