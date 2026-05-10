import { useEffect, useMemo, useState } from 'react'

import { PlanningMap } from './components/PlanningMap'
import {
  DEFAULT_BBOX,
  DEFAULT_SOURCES,
} from './config/noiseMap'
import { postCalculate } from './lib/api'
import type { BarrierRing, BarrierType } from './lib/api'
import { bboxCenter, gridToConflictMask, gridToNoisePolygons } from './lib/geo'

import './App.css'

const MAPBOX_TOKEN = import.meta.env.VITE_MAPBOX_ACCESS_TOKEN ?? ''
const API_BASE =
  import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

const POPULATION_PER_CELL = 2.5
const CONFLICT_THRESHOLD_DB = 45
const ECO_SCORE_PER_100M_GREEN = 15

function App() {
  const [noisePolygons, setNoisePolygons] = useState<GeoJSON.FeatureCollection>(() => ({
    type: 'FeatureCollection',
    features: [],
  }))
  const [conflictMask, setConflictMask] = useState<GeoJSON.FeatureCollection | null>(null)
  const [conflictStats, setConflictStats] = useState({ cellCount: 0, areaHa: 0, population: 0 })
  const [baselineCells, setBaselineCells] = useState<number | null>(null)
  const [weighting, setWeighting] = useState<'DBA' | 'DBC'>('DBA')
  const [loading, setLoading] = useState(true)
  const [errorText, setErrorText] = useState<string | null>(null)
  const [barriers, setBarriers] = useState<BarrierRing[]>([])
  const [barrierType, setBarrierType] = useState<BarrierType>('concrete')
  const [drawingMode, setDrawingMode] = useState(false)
  const [drawPoints, setDrawPoints] = useState<[number, number][]>([])
  const [savedResidents, setSavedResidents] = useState(0)
  const [showToast, setShowToast] = useState(false)
  const [ecoScore, setEcoScore] = useState(0)

  const cellSizeM = 85

  const requestBody = useMemo(
    () => ({
      bbox: DEFAULT_BBOX,
      sources: DEFAULT_SOURCES.map((s) => ({ ...s })),
      weighting,
      cell_size_m: cellSizeM,
      A_abs: 8.0,
      barriers: barriers.length > 0 ? barriers : undefined,
    }),
    [weighting, barriers],
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

        // Save baseline (0 barriers) on first load, compute saved residents from difference
        if (baselineCells === null) {
          setBaselineCells(cellCount)
          setSavedResidents(0)
        } else if (barriers.length > 0 && cellCount < baselineCells) {
          const saved = Math.round((baselineCells - cellCount) * POPULATION_PER_CELL)
          setSavedResidents(saved)
          if (saved > 0) {
            setShowToast(true)
            setTimeout(() => setShowToast(false), 4000)
          }
        } else {
          setSavedResidents(0)
        }

        // Compute eco-score: +15% per 100m of green wall perimeter
        let score = 0
        for (const b of barriers) {
          if (b.type === 'green') {
            // Approximate perimeter from ring coords (WGS84 → rough meters)
            let perimM = 0
            for (let i = 0; i < b.ring.length - 1; i++) {
              const [lng1, lat1] = b.ring[i]
              const [lng2, lat2] = b.ring[i + 1]
              const dlat = (lat2 - lat1) * 111320
              const dlng = (lng2 - lng1) * 111320 * Math.cos((lat1 + lat2) / 2 * (Math.PI / 180))
              perimM += Math.sqrt(dlat * dlat + dlng * dlng)
            }
            score += Math.round((perimM / 100) * ECO_SCORE_PER_100M_GREEN)
          }
        }
        setEcoScore(score)
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

  function handleMapClick(lonlat: [number, number]) {
    if (!drawingMode) return
    const next = [...drawPoints, lonlat]
    if (next.length === 2) {
      const [p0, p1] = next
      const ring: [number, number][] = [
        [p0[0], p0[1]],
        [p1[0], p0[1]],
        [p1[0], p1[1]],
        [p0[0], p1[1]],
        [p0[0], p0[1]],
      ]
      setBarriers(prev => [...prev, { ring, type: barrierType }])
      setDrawPoints([])
      setDrawingMode(false)
    } else {
      setDrawPoints(next)
    }
  }

  function clearBarriers() {
    setBarriers([])
    setDrawPoints([])
    setSavedResidents(0)
    setShowToast(false)
    setEcoScore(0)
    // Reset baseline so next load re-captures it
    setBaselineCells(null)
  }

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
        barriers={barriers}
        drawingMode={drawingMode}
        drawPoints={drawPoints}
        onMapClick={handleMapClick}
        toastMessage={
          showToast && savedResidents > 0
            ? `Mitigation Active: ${savedResidents} Residents Protected`
            : null
        }
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

        <div className="panel" style={{ marginTop: 12 }}>
          <div className="panel-title">Buffer optimizer (§3.5)</div>

          {/* Barrier type toggle */}
          <div className="toggle-row" style={{ marginBottom: 10 }}>
            <button
              type="button"
              className={barrierType === 'concrete' ? 'active' : ''}
              onClick={() => setBarrierType('concrete')}
              style={{ flex: 1, borderRadius: 10, border: '1px solid #cbd5e1', background: barrierType === 'concrete' ? '#0f172a' : '#f8fafc', color: barrierType === 'concrete' ? '#f8fafc' : '#0f172a', padding: '8px 10px', cursor: 'pointer', fontWeight: 600, fontSize: 11 }}
            >
              Concrete (-20 dB)
            </button>
            <button
              type="button"
              className={barrierType === 'green' ? 'active' : ''}
              onClick={() => setBarrierType('green')}
              style={{ flex: 1, borderRadius: 10, border: '1px solid #cbd5e1', background: barrierType === 'green' ? '#065f46' : '#f8fafc', color: barrierType === 'green' ? '#f8fafc' : '#065f46', padding: '8px 10px', cursor: 'pointer', fontWeight: 600, fontSize: 11 }}
            >
              Green Wall (-12 dB)
            </button>
          </div>

          <button
            type="button"
            style={{
              width: '100%', borderRadius: 10, border: '1px solid #cbd5e1',
              background: drawingMode ? '#0f172a' : '#f8fafc',
              color: drawingMode ? '#f8fafc' : '#0f172a',
              padding: '8px 10px', cursor: 'pointer', fontWeight: 600,
            }}
            onClick={() => { setDrawingMode(!drawingMode); setDrawPoints([]) }}
          >
            {drawingMode ? 'Cancel' : 'Place barrier'}
          </button>
          {drawingMode && (
            <p className="muted small" style={{ marginTop: 8 }}>
              Click two map corners to place a rectangular {barrierType} barrier.
            </p>
          )}
          {barriers.length > 0 && (
            <button
              type="button"
              onClick={clearBarriers}
              style={{
                width: '100%', borderRadius: 10, border: '1px solid #e74c3c',
                background: '#fef2f2', color: '#7f1d1d',
                padding: '8px 10px', cursor: 'pointer', fontWeight: 600, marginTop: 8,
              }}
            >
              Clear barriers ({barriers.length})
            </button>
          )}
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
          {savedResidents > 0 && (
            <div className="metric-row victory-row" style={{ borderBottom: 'none', marginTop: 4 }}>
              <span className="metric-label victory-label">Residents saved</span>
              <span className="metric-value victory-value">~{savedResidents}</span>
            </div>
          )}
          {ecoScore > 0 && (
            <div className="metric-row" style={{ borderBottom: 'none', marginTop: 4 }}>
              <span className="metric-label" style={{ color: '#065f46', fontWeight: 700, fontSize: 13 }}>Urban Cooling / Eco-Score</span>
              <span className="metric-value" style={{ color: '#047857', fontWeight: 800, fontSize: 16 }}>+{ecoScore}%</span>
            </div>
          )}
        </div>
      </aside>
    </div>
  )
}

export default App