/**
 * §5.1 heatmap tuning — density is kernel-smoothed; SPL anchors are qualitative:
 * green ≈ &lt;40 dB, yellow→orange 40–55 dB, red ≈ &gt;55 dB.
 */
export const HEATMAP_RADIUS_PIXELS = 62
export const HEATMAP_INTENSITY = 1.35
export const HEATMAP_THRESHOLD = 0.05

/** RGBA stops from quiet → loud (deck.gl normalizes internally). */
export const HEATMAP_COLOR_RANGE: [number, number, number, number][] = [
  [46, 204, 113, 220],
  [241, 196, 15, 230],
  [230, 126, 34, 235],
  [231, 76, 60, 240],
]

/** Santa Clara / “data center alley” demo extent — mirrors backend OSM preset. */
export const DEFAULT_BBOX = {
  min_lon: -122.02,
  min_lat: 37.36,
  max_lon: -121.965,
  max_lat: 37.415,
} as const

export const DEFAULT_SOURCES = [
  { lon: -121.985, lat: 37.378, reference_level_db: 78 },
  { lon: -121.988, lat: 37.388, reference_level_db: 76 },
] as const
