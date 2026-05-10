import type { BBox } from './geo'

export type AcousticWeighting = 'DBA' | 'DBC'

export type NoiseSourcePayload = {
  id?: string
  lon: number
  lat: number
  reference_level_db: number
  cooling_mw?: number
}

export type BarrierType = 'concrete' | 'green'

export type BarrierRing = {
  ring: number[][]
  type?: BarrierType
}

export type CalculateRequest = {
  bbox: BBox
  sources: NoiseSourcePayload[]
  weighting: AcousticWeighting
  cell_size_m: number
  A_abs?: number
  barriers?: BarrierRing[]
}

export type CalculateResponse = {
  rows: number
  cols: number
  cell_size_m: number
  weighting: string
  A_abs: number
  grid_db: number[][]
  zoning_mask: string[][]
  barriers_applied: number
}

export async function postCalculate(
  baseUrl: string,
  body: CalculateRequest,
): Promise<CalculateResponse> {
  const res = await fetch(`${baseUrl.replace(/\/$/, '')}/calculate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) {
    const text = await res.text()
    throw new Error(`calculate failed (${res.status}): ${text}`)
  }
  return res.json() as Promise<CalculateResponse>
}
