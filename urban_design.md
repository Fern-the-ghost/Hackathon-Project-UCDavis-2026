# Urban Design: Data Center Noise & Urban Development Planning Tool

This document outlines architecture and product design for a planning tool that visualizes **24/7 acoustic footprints** from industrial cooling (data centers), combines **OpenStreetMap** land-use zoning, and surfaces **residential conflict zones** where projected levels exceed sleep-health guidance (e.g., **45 dB** EPA-recommended limit for sleep disturbance risk).

**Reference region:** High-density urban corridors such as Santa Clara / Silicon Valley—many ground-adjacent assets, mixed residential parcels, and cumulative low-frequency “hum” from multiple facilities.

---

## 1. Product Goals & Constraints

| Goal | Notes |
|------|--------|
| Place industrial sources | Users add **Industrial Points** with cooling-scale presets (e.g., 50 MW vs 100 MW) mapped to representative **dB at reference distance** (document assumptions; tune with calibration). |
| Physics-informed decay | **Ground-level / area-source** behavior with **low-frequency emphasis**: use a dedicated decay path (below), not pure spherical “point-in-air” aviation models. |
| Zoning context | Pull OSM tags for **Residential**, **Commercial**, **Public** (and optionally Industrial) to classify parcels or raster cells. |
| Conflict visualization | Highlight residential areas where modeled **24/7 equivalent or nighttime level** exceeds **45 dB** threshold (configurable). |
| Dual-frequency analysis | User-selectable **dBA** (A-weighted, hearing-sensitive) vs **dBC** (C-weighted, low-frequency / vibration-relevant) propagation curves (§3.2–3.3). |
| Barrier buffers | **Buffer Buildings** with **ray-intersection shadow zones** and prescribed attenuation toward residential receivers (§3.5). |

**Non-goals (initial phase):** Regulatory compliance sign-off, diffraction around barrier edges, multi-bounce reflections, or full meteorological time-series—those can be future extensions.

---

## 2. Backend Architecture (Python / FastAPI)

### 2.1 High-Level Shape

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│  FastAPI API    │────▶│  Grid Engine     │────▶│  Tile / GeoJSON │
│  (REST + jobs)  │     │  (NumPy / Numba) │     │  responses      │
└────────┬────────┘     └────────┬─────────┘     └─────────────────┘
         │                       │
         │              ┌────────▼─────────┐
         └──────────────▶ OSM Ingest      │
                        │ (Overpass/cache)│
                        └─────────────────┘
```

- **API layer:** Bounding box + resolution + sources + thresholds → returns grid statistics, conflict masks, and optional vector summaries.
- **Compute layer:** Pure numerical grid operations (fast, testable, GPU-optional later).
- **Data layer:** Cached OSM extracts (file or DB) keyed by bbox + tag schema version.

### 2.2 Core Data Structures

- **`NoiseSource`**  
  - `id`, `lon_lat`, `reference_level_db` (e.g., at 10 m or at facility fence), `cooling_mw` (metadata), `footprint_radius_m` or polygon for **area source** approximation.
- **`AcousticWeighting`**  
  - Enum: **`DBA`** | **`DBC`**. Drives effective absorption in decay (§3.2) and should be echoed in API responses for reproducibility.
- **`BufferBuilding`**  
  - `id`, footprint **polygon** (metric or WGS84), optional height metadata for future 3D; used only for **2D ray–segment intersection** against source→cell rays (§3.5).
- **`GridSpec`**  
  - origin `(lon0, lat0)`, width/height in meters or degrees, `cell_size_m`, CRS (project to **metric CRS** for distances—e.g., Web Mercator locally or UTM zone for the bbox).
- **`ZoningRaster` or `ZoningVector`**  
  - Per-cell or per-feature classification: `RESIDENTIAL | COMMERCIAL | PUBLIC | INDUSTRIAL | OTHER`.
- **`NoiseField`**  
  - 2D matrix `L[row, col]` in dB. Internally accumulate **linear intensity** per cell until all sources (and barrier adjustments) are applied—see **§3.4 Cumulative exposure**.

### 2.3 Processing Pipeline

1. **Normalize bbox** → metric projection → build row/col index ↔ world coordinates.
2. **Fetch / attach zoning**  
   - Query OSM (Overpass API or local `.osm.pbf` + `pyosmium`) for `landuse`, `zoning` (where present), `amenity`, `leisure`, `boundary` relations—map coarsely to the three user-facing buckets plus industrial.
3. **Rasterize zoning** (optional): polygons → cell majority vote or fractional overlay for mixed-use cells.
4. **Resolve acoustic weighting**  
   - Accept `weighting: "DBA" | "DBC"` on the session or grid request. Map to effective absorption \(A_{\text{abs}}\) per §3.2 (**dBC** uses **50%** of the nominal absorption term).
5. **Per-source contributions**  
   - For each industrial source and each grid cell, compute baseline \(L_{\text{ground}}\) (§3.2). If §3.5 applies: for **residential** cells whose ray from **source centroid → cell center** intersects any **Buffer Building** footprint, treat path as shadowed and subtract **12 dB** from **that source’s** contribution at that cell **before** energy summation.
6. **Cumulative exposure (energy addition)**  
   - For each cell, \(L_{\text{total}} = 10 \log_{10}\!\left(\sum_i 10^{L_i/10}\right)\) over all contributing sources \(i\) (after shadow adjustments). This models **Santa Clara–style clusters** where multiple data centers compound exposure.
7. **Conflict mask**  
   - `conflict = (zoning == RESIDENTIAL) & (L > threshold_db)` with configurable threshold default **45 dB** (interpret in the active weighting unless dual maps are requested).
8. **Downsample / tile**  
   - Return GeoTIFF-like payloads or vector contours for Mapbox; precompute low-res for sidebar previews.

### 2.4 API Endpoints (Sketch)

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/session/grid` | Body: bbox, resolution, sources, **`weighting`**, **`buffer_buildings[]`** → returns job id or sync result |
| `GET` | `/session/{id}/field` | Noise grid metadata + URL or inline compressed array |
| `GET` | `/session/{id}/conflicts` | GeoJSON polygons or raster mask for residential exceedances |
| `POST` | `/analyze/viability` | Body: `coord` → `HealthScore` (§4) |
| `POST` | `/optimize/buffer` | Body: candidate footprints → delta on conflicts / score (may reuse §3.5 shadow logic for **Buffer Building** class) |

Use **background tasks** (e.g., Celery/RQ) if bbox + resolution makes grids heavy; for hackathon scope, cap grid size server-side.

**`POST /analyze/viability`** should accept optional **`local_timestamp`** or **`timezone` + `clock_time`** (or **`is_nighttime`**) so §4.3 **+10 dB nighttime adjustment** on **`predicted_db`** is deterministic.

### 2.5 Dependencies (Planning-Level)

- **FastAPI**, **Pydantic** for schemas  
- **NumPy** (+ optional **Numba**) for hot loops  
- **GeoPandas / Shapely / Rasterio** or lightweight rasterizer for zoning overlap  
- **HTTP client** for Overpass + disk cache  
- **pytest** for physics and viability golden tests  

---

## 3. Acoustic Model: Ground Sources, Dual Weighting, Barriers & Clusters

### 3.1 Design Intent

Data centers behave more like **extended ground-level radiators** (cooling plant yards, CT arrays) than compact airborne points. The tool exposes **two listening curves**:

- **dBA (A-weighted):** Approximates **human hearing sensitivity**—useful for communicating perceived loudness and typical environmental noise ordinances framed around A-weighting.
- **dBC (C-weighted):** More uniform at low frequencies—better highlights **low-frequency hum / structure-borne cues** that penetrate façades and dominate complaint narratives.

Propagation still uses a **transparent parametric** decay so planners can compare curves without implying laboratory-grade precision.

### 3.2 Baseline Formula (Per Source–Receiver Pair)

For each cell center at distance \(d\) (meters, projected CRS), use:

\[
L_{\text{ground}} = L_{\text{source}} - 20 \log_{10}(d) - A_{\text{eff}}
\]

- **`L_source`**: Reference SPL at a declared baseline (fence line, 10 m, etc.), mapped from cooling presets.
- **`20 log10(d)`**: Ground-hugging spreading baseline (v2 may swap exponent for line arrays).
- **`A_abs` (nominal):** Urban excess attenuation / absorption aggregate from calibration (land cover, canopy placeholders). **Do not confuse with barrier shadow—that is §3.5.**

**Dual-frequency rule (toggle `DBA` vs `DBC`):**

Let \(A_{\text{abs}}\) be the nominal absorption coefficient from calibration.

| Weighting | Effective absorption in decay | Rationale |
|-----------|----------------------------------|-----------|
| **dBA** | \(A_{\text{eff}} = A_{\text{abs}}\) | Standard attenuation profile for mid-frequency-weighted perception. |
| **dBC** | \(A_{\text{eff}} = 0.5 \cdot A_{\text{abs}}\) | **Halve** the subtractive absorption term so low-frequency **hum carries farther** through urban fabric than in the A-weighted mental model—consistent with reduced atmospheric/building absorption at bass-heavy content. |

All \(L\) values presented while **dBC** is selected should be labeled **dBC**; likewise **dBA** when that mode is active.

**Area sources:** Subdivide footprints into **sub-panels** with \(L_{\text{source}} - 10\log_{10}(N)\) per panel; compute \(L_{\text{ground}}\) from each panel centroid to the receiver and combine panels via **§3.4** before merging distinct facilities.

### 3.3 Metrics & Maps

- **Single-map mode:** One active weighting drives heatmap + conflicts + viability sampling.
- **Optional dual-overlay (future):** Side-by-side or blended raster when comparing ordinances (dBA) vs low-frequency concern (dBC).
- **24/7 framing:** Maps remain **steady cumulative outdoor levels**; **health scoring** adds explicit **nighttime sensitivity** (§4.4)—distinct from changing the acoustic physics toggle.

### 3.4 Cumulative Exposure (Multi-Facility Clusters)

Santa Clara–scale planning requires **incoherent energy addition** across independent industrial contributors. After computing each source’s **shadow-adjusted** level \(L_i\) at a cell (§3.5 applies per source):

\[
L_{\text{total}} = 10 \log_{10}\left(\sum_{i} 10^{L_i/10}\right)
\]

Implementation detail: maintain **`intensity[row,col] += 10^(L_i/10)`** in float64, then `L_total = 10*log10(intensity)` once all sources are processed—numerically stable versus repeated pairwise dB sums.

### 3.5 Barrier Simulation: “Place Buffer” & Ray Intersection

**Feature:** **Place Buffer** — user drops one or more **Buffer Building** footprints (axis-aligned rectangle or free polygon in UI; stored as metric polygons server-side).

**Shadow test (2D, per source \(s\) and cell \(c\)):**

1. Let \(P_s\) be the **effective source point** (facility centroid or panel centroid when using area decomposition).
2. Let \(P_c\) be the **cell center**.
3. Cast ray \(\overrightarrow{P_s P_c}\).
4. **Ray–polygon intersection:** If the segment \(P_s \rightarrow P_c\) intersects the interior or boundary of any **Buffer Building** polygon (standard computational geometry; treat degenerate grazing hits consistently), mark cell \(c\) as **shadowed from source \(s\)** by that buffer.

**Attenuation rule (residential only):**

If **`zoning(c) == RESIDENTIAL`** and \(c\) is shadowed from \(s\) per above, apply **−12 dB** to **that source’s contribution only**:

\[
L_{s,c}^{\,\prime} = L_{s,c} - 12\;\text{dB}
\]

Then feed \(L_{s,c}^{\,\prime}\) into §3.4 summation for facility totals. Non-residential cells remain unshielded by this rule (commercial/industrial land keeps full coupling unless extended later).

**Multiple buffers / sources:** Evaluate intersection against the **union of placements** or **any** intersected polygon—simplest MVP: **any** barrier crossing the segment triggers shadowing. Order along the ray matters only if modeling stacked barriers; MVP assumes **one −12 dB credit per shadowed source path** (not stacked multipliers unless explicitly extended).

**Visualization:** Optional diagonal hatch fill for “shadow cone” footprint projected on ground is misleading in 2D; prefer **highlighting residential cells** receiving barrier credit or drawing buffer outlines—advanced: wedge preview from selected source.

### 3.6 Calibration Hooks

- YAML / DB: `cooling_mw → L_source`, spreading exponent, **`A_abs` by land-cover** and by **`AcousticWeighting`** if divergent priors are needed later.
- Barrier: **`shadow_attenuation_db`** default **12**, configurable.
- Golden tests: two equal sources at same distance → **+3 dB** total; shadowed residential cell drops **12 dB** vs unshadowed at same geometry.

---

## 4. Zoning Logic: `assess_development_viability(coord)`

### 4.1 Purpose

Given a **single coordinate** (proposed residential infill, school, hospital, or park), return a **Health Score** summarizing predicted noise exposure relative to guidelines and zoning context.

### 4.2 Inputs

- `coord`: `(lon, lat)`  
- Implicit / contextual: current `NoiseField` (must match active **`AcousticWeighting`**), `ZoningRaster`, buffers used for that grid  
- Config: `threshold_sleep_db` (default **45**), zoning weights  
- **Temporal context:** `local_timestamp` (**timezone-aware ISO-8601**) **or** `timezone` (IANA string) + `clock_time` **or** explicit **`is_nighttime`** flag—needed for §4.3 nighttime adjustment.

### 4.3 Computation Sketch

1. **Sample physical noise** at `coord` (bilinear interp on grid)—same weighting as displayed map (**dBA** or **dBC**). Call this \(L_{\text{phys}}\).
2. **Nighttime adjustment (`predicted_db`):** If **`is_nighttime`** is true (derived from local clock **22:00–07:00** or passed explicitly), apply a fixed **+10 dB penalty** to the value used for viability and reporting:
   \[
   L_{\text{pred}} = L_{\text{phys}} + \begin{cases} 10\;\text{dB} & \text{if nighttime} \\ 0 & \text{otherwise} \end{cases}
   \]
   The API field **`predicted_db`** MUST reflect \(L_{\text{pred}}\) (effective exposure). Optionally also return **`predicted_db_physical`** = \(L_{\text{phys}}\) for transparency.
3. **Classify zoning** at `coord` (point-in-polygon or nearest raster cell).
4. **Exposure penalty**  
   - Define excess from the **effective** level: \(E = \max(0, L_{\text{pred}} - threshold)\).
   - **Weighted penalty:** \(P = k \cdot E^{p} \cdot zoning_multiplier\) with tunable \(k,p\) (e.g., \(p=2\) from prior sketch)—**nighttime severity is captured by the +10 dB on \(L_{\text{pred}}\)** rather than a separate multiplicative factor.
5. **Health Score**  
   - `score = clamp(100 - P, 0, 100)` (keep monotone decreasing in \(E\)).
6. **Returned payload (conceptual)**

```text
{
  "coord": [lon, lat],
  "predicted_db_physical": float,
  "predicted_db": float,
  "weighting": "DBA|DBC",
  "zoning": "RESIDENTIAL",
  "threshold_db": 45,
  "exceedance_db": float,
  "local_time_context": { "is_nighttime": true, "window": "22:00-07:00" },
  "night_db_penalty_applied": 10,
  "health_score": int,
  "risk_band": "LOW|MED|HIGH",
  "notes": ["Within residential zone", "Nighttime assessment (+10 dB on predicted_db)"]
}
```

### 4.4 Testing Strategy

- Synthetic single-source closed-form checks at known distances.
- Known-quiet vs known-noisy cells under synthetic zoning masks.
- **Energy addition:** two equal contributors → **+3 dB** at overlap cell.
- **Nighttime:** for fixed \(L_{\text{phys}}\), **`predicted_db`** MUST increase by **exactly 10 dB** when **`is_nighttime`** is true; **`exceedance_db`** MUST use **`predicted_db`**.
- **Barriers:** residential cell behind buffer vs identical cell without intersection → **12 dB** lower contribution from occluded source before sum.

---

## 5. Frontend Architecture (React + Mapbox)

### 5.1 Visualization strategy (cumulative noise field)

**Do not** use animated vehicle/trip visualizations or transit demos—they distract from **stationary industrial hum**. The **primary** noise view is a Mapbox GL **`heatmap`** layer (**`type: 'heatmap'`**) driven by the **cumulative** sound field \(L_{\text{total}}\) from §3.4.

**Data feeding the HeatmapLayer**

- Backend returns the noise grid (or sampled **GeoJSON** points at cell centers). Each feature carries **`properties.db`** = \(L_{\text{total}}\) for that cell (after barriers and multi-source energy sum—**not** the nighttime +10 dB viability adjustment from §4.3; the map shows **physical** modeled levels).
- Set **`heatmap-weight`** from **linear acoustic intensity** so overlapping contributions behave consistently with “loudness mass”, e.g. **`weight = Math.pow(10, db / 10)`** (optionally normalized per view).
- Tune **`heatmap-radius`**, **`heatmap-intensity`**, and (if needed) **`heatmap-opacity`** once per style so the layer reads well at city scale.

**Color scale (required)**

- **`heatmap-color`**: `interpolate` on **`heatmap-density`** such that the ramp is **green for quiet** and **red for loud**, anchoring **SPL semantics** as follows:
  - **Green** end maps to **\< 40 dB**.
  - **Red** end maps to **\> 55 dB**.
  - **40–55 dB**: yellow → orange band between those anchors (explicit intermediate stops recommended).
- Because **`heatmap-density`** is kernel-smoothed—not raw dB in screen space—**calibrate** `heatmap-radius`, `heatmap-intensity`, and color stops against synthetic fixtures until spot checks satisfy **\<40 reads green** and **\>55 reads red**; document constants in frontend config.

**Legend**

- Fixed color bar with ticks at **40 dB** and **55 dB** aligned to the green/red anchors; label active **`AcousticWeighting`** (**dBA** vs **dBC**).

### 5.2 Layer Stack

| Layer | Role |
|-------|------|
| **Layer 1 — Base map** | Mapbox GL base style (light/dark); metric projection awareness for overlays. |
| **Layer 2 — Cumulative noise (`heatmap`)** | **`HeatmapLayer`** over grid-derived GeoJSON points (§5.1). Updates when sources, **buffers**, **`weighting`**, or bbox change; debounce API calls. |
| **Layer 3 — Zoning tint** | Semi-transparent fill by OSM-derived classification (Residential / Commercial / Public). |
| **Layer 4 — Conflict mask** | Bold hatch / red fill **only** where residential ∧ \(L > threshold\) in the **active weighting**; tooltip shows **dBA or dBC** value + threshold context. |
| **Layer 5 — Industrial Points** | Draggable markers with MW presets and level preview. |
| **Layer 6 — Buffer Buildings (Place Buffer)** | User-drawn or dropped footprints (fill + outline). Passed verbatim to backend for §3.5 ray checks; distinct styling from zoning (e.g., teal dashed outline). |

### 5.3 Controls: Dual-Frequency Modeling

- Prominent **toggle** or segmented control: **“Hearing (dBA)”** vs **“Low-frequency (dBC)”**.
- On switch: re-request `/session/grid` with `weighting` flag and **refresh the heatmap source** (instant swap or short opacity fade—**no** trip-style animation).
- Inline helper copy: **dBA** ≈ perceived loudness; **dBC** emphasizes **hum / vibration-relevant** propagation (farther reach via reduced \(A_{\text{eff}}\) on backend).
- Threshold presets may stay fixed numerically but **interpretation** differs—surface short disclaimer in sidebar.

### 5.4 State & Data Flow

- Global/store: `sources[]`, **`bufferBuildings[]`** (GeoJSON polygons), **`weighting: 'DBA' | 'DBC'`**, `bbox`, `gridVersion`, `thresholdDb`, **`viabilityClock`** / **`is_nighttime`** (for `/analyze/viability`; §4.3 **+10 dB** on **`predicted_db`** only—heatmap stays physical \(L_{\text{total}}\)), `loading/error`.
- On change: `POST /session/grid` with **sources + buffers + weighting** → update **`heatmap`** GeoJSON source + conflict overlays + cached viability inputs.

### 5.5 Sidebar: Development Optimizer & Place Buffer

**Purpose:** Reduce residential conflicts via **deliberate buffering**—now backed by **ray-intersection shadow** physics rather than only heuristic ΔdB blobs.

**Place Buffer workflow:**

1. User activates **“Place Buffer”** mode → draw rectangle / polygon or stamp a template footprint (warehouse slab, berm footprint).
2. Footprint syncs to `bufferBuildings[]`; triggering recomputation shows updated heatmap (residential cells in §3.5 shadows drop contribution **−12 dB** per occluded source path).
3. Optional debug toggle: **show rays** from selected industrial point through buffers (expensive—sample subset only) or highlight residential cells receiving barrier credit.

**Optimizer (retained / upgraded):**

1. **Suggest placement:** coarse grid search along residential–industrial interfaces maximizing **conflict pixel reduction** under §3.5 + §3.4 pipeline.
2. Rank suggestions; ghost overlays remain clickable.

### 5.6 Performance

- Cap frontend refresh rate; use Web Workers for decoding compressed grids if needed.
- Static OSM zoning for bbox cached client-side after first load.
- Ray intersection is **server-bound**; keep polygon counts modest or simplify footprints before POST.

---

## 6. OSM Tag → Zoning Bucket Mapping (Initial Heuristic)

| Bucket | Example OSM signals |
|--------|---------------------|
| **Residential** | `landuse=residential`, `residential=*`, some `place=suburb` polygons |
| **Commercial** | `landuse=commercial`, `shop=*` areas, `amenity=marketplace` |
| **Public** | `amenity=school`, `leisure=park`, `amenity=hospital`, `landuse=civic` |
| **Industrial** | `landuse=industrial`, `man_made=works` |

Ambiguity: many regions lack official `zoning=*`; **fallback** = infer from building density + landuse or show “unknown” with muted styling.

---

## 7. Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| Physics oversimplified | Clear UI disclaimers; calibration file; sensitivity slider for `A_abs`. |
| OSM incompleteness | Allow CSV/geojson zoning upload for demos; highlight low-confidence areas. |
| Large grids slow | Progressive LOD; smaller default bbox; async jobs. |
| Legal perception | Position as **planning aid**, not regulatory compliance. |

---

## 8. Implementation Phases

1. **Phase A:** FastAPI + synthetic bbox + multi-source grid + **energy addition (§3.4)** + React Mapbox heatmap + **dBA/dBC toggle**.  
2. **Phase B:** OSM ingest + zoning layers + conflict mask + `assess_development_viability` + **nighttime multiplier (§4.4)**.  
3. **Phase C:** **Place Buffer** UI + **ray-intersection shadow** §3.5 + area-source panelization + calibration YAML + optimizer leveraging real barrier logic.

---

## 9. Open Questions (Decide Before Coding)

- Reference distance for `L_source` (10 m vs property line vs centroid).
- Whether **45 dB** is displayed as **absolute modeled level** or **normalized indoor estimate**—and whether thresholds should **differ by weighting** (likely yes for rigorous studies; MVP may keep one number with clear labeling).
- CRS choice per bbox (single UTM zone vs Web Mercator tolerance).
- Exact MW → dB mapping source (literature vs placeholder curve).
- **Nighttime window:** inclusive boundaries and DST handling for `America/Los_Angeles` demos (Santa Clara).
- **Barrier:** whether commercial/public sensitive sites should optionally receive shadow credit (currently residential-only per §3.5).

---

*This document is the agreed planner specification prior to implementation.*
