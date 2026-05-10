/**
 * §5.1 heatmap tuning — density is kernel-smoothed; SPL anchors are qualitative:
 * green ≈ &lt;40 dB, yellow→orange 40–55 dB, red ≈ &gt;55 dB.
 */
export const HEATMAP_RADIUS_PIXELS = 62
export const HEATMAP_INTENSITY = 1
export const HEATMAP_THRESHOLD = 0.3

/** §5.1 guardrails: first stop transparent [0,0,0,0], then green→yellow→orange→red.
 *  deck.gl normalizes internally; green ≈ <40 dB, red ≈ >55 dB. */
export const HEATMAP_COLOR_RANGE: [number, number, number, number][] = [
  [0, 0, 0, 0],
  [46, 204, 113, 220],
  [241, 196, 15, 230],
  [230, 126, 34, 235],
  [231, 76, 60, 240],
]

/** §5.1 color stops for the GeoJsonLayer noise field — same palette as HEATMAP_COLOR_RANGE. */
export const NOISE_COLOR_STOPS: [number, number, number, number][] = [
  [0, 0, 0, 0],        // transparent (≤40 dB)
  [46, 204, 113, 220], // green (~40-45 dB)
  [241, 196, 15, 230], // yellow (~45-50 dB)
  [230, 126, 34, 235], // orange (~50-55 dB)
  [231, 76, 60, 240],  // red (≥55 dB)
]

/** Santa Clara / “data center alley” demo extent — mirrors backend OSM preset. */
export const DEFAULT_BBOX = {
  min_lon: -122.02,
  min_lat: 37.36,
  max_lon: -121.965,
  max_lat: 37.415,
} as const

export const DEFAULT_SOURCES = [
  { lon: -121.985, lat: 37.378, reference_level_db: 105 },
  { lon: -121.988, lat: 37.388, reference_level_db: 103 },
] as const
