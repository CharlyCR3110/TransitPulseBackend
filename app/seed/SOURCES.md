# Seed data provenance

> Last updated: 2026-05-16.
> Captures *where each fact in the seed came from* and on what date, so
> reviewers can re-verify and stakeholders know what's measured vs estimated.

## Routes

### `100`, `205`, `302`, `T1`, `T2` — toy seed (MLP)

Synthetic data hand-crafted during the MLP. Used by the existing 17-row smoke
checklist. Kept verbatim to avoid regressing those tests. Replace post-M3 once
real corridor data covers the same demo flows.

### `400p` — Heredia ↔ San José POR PISTA — autopista corridor

| Field | Source | Captured | Notes |
|---|---|---|---|
| Route name | Moovit | 2026-05-07 | "HEREDIA - SAN JOSÉ POR PISTA" |
| Operator | Moovit + WebSearch | 2026-05-07 | Transportes Unidos La 400 S.A. |
| Stops (11 outbound, 24 inbound) | [Moovit PDF](https://appassets.mvtdev.com/map/188/l/2967/48315295.pdf) + `.sop/planning/transitpulse-m2/research/heredia-routes.md` | 2026-05-16 | Outbound = stops 1–11 of the 32-stop loop PDF (Heredia → SJ leg only). Inbound = 24-stop dedicated SJ→Heredia PDF. See "Loop-split decision" below. |
| Trip duration | Moovit PDF | 2026-05-07 | 32 min outbound / 26 min inbound |
| Hours of operation | Moovit PDF | 2026-05-07 | Daily 05:00 – 22:00 |
| Headway | **Estimated** | 2026-05-07 | Operator does not publish; used 12 / 15 / 20 min for weekday/sat/sun. Verify with operator before stakeholder demo. |
| Fare (CRC) | **Placeholder** | 2026-05-07 | 750 CRC — peer-route reference for ~14 km GAM corridor. ARESEP tariff page is JS-rendered; need separate fetch or operator confirmation. |
| Polyline shape | **Anchor-only** | 2026-05-07 | LineString through anchor stops, not road-snapped. M3 should run OSRM with bus-friendly profile. |

### `400u` — Heredia ↔ San José POR LA URUCA — urban via Aurora, Barreal, Lagunilla

| Field | Source | Captured | Notes |
|---|---|---|---|
| Route name | Moovit | 2026-05-16 | "HEREDIA - SAN JOSÉ POR LA URUCA" |
| Operator | Moovit | 2026-05-16 | Transportes Unidos La 400 S.A. |
| Stops (47 outbound, 48 inbound) | [Moovit PDF](https://appassets.mvtdev.com/map/188/l/2967/47829186.pdf) + `heredia-routes.md` | 2026-05-16 | Full bi-directional sequence. Goes Terminal Heredia (Predio La 400, Pirro) → Santa Cecilia → La Aurora → Barreal → Lagunilla → La Uruca → Terminal SJ. |
| Trip duration | Moovit PDF | 2026-05-16 | 38 min outbound / 38 min inbound |
| Headway | **Not yet captured** | — | Operator does not publish; placeholder needed before demo. Use 400p defaults until verified. |
| Fare (CRC) | **Placeholder** | 2026-05-16 | 750 CRC — same operator and similar corridor length as 400p. Replace with ARESEP value. |
| Polyline shape | **Anchor-only** | 2026-05-16 | Same caveat as 400p. |

### `400sd` — San José ↔ Heredia POR SANTO DOMINGO — urban corridor (24/7)

| Field | Source | Captured | Notes |
|---|---|---|---|
| Route name | Moovit | 2026-05-07 | "SAN JOSÉ - HEREDIA POR SANTO DOMINGO" |
| Operator | Moovit | 2026-05-07 | Microbuses Rápidos Heredianos S.A. (MRH) |
| Stops (34 outbound, 40 inbound) | [Moovit PDF](https://appassets.mvtdev.com/map/188/l/2967/48315296.pdf) + `heredia-routes.md` | 2026-05-16 | Full bi-directional sequence. Outbound (Heredia→SJ) is the 34-stop list; inbound (SJ→Heredia) is the 40-stop list. |
| Trip duration | Moovit PDF | 2026-05-07 | 27 min outbound / 34 min inbound |
| Hours of operation | Moovit PDF | 2026-05-07 | **24 horas** — service runs around the clock |
| Headway | **Estimated** | 2026-05-07 | Operator does not publish; used 10 / 15 / 20 min for weekday/sat/sun. |
| Fare (CRC) | **Placeholder** | 2026-05-07 | 720 CRC — placeholder; ARESEP MRH tariff page needed for verification. |
| Polyline shape | **Anchor-only** | 2026-05-07 | LineString through anchor stops, not road-snapped. |

### Loop-split decision (400p, 2026-05-16)

Moovit's 400p outbound PDF is a 32-stop **loop** (Terminal Heredia → SJ → back to Terminal Heredia). For the planner, treating the entire loop as one logical direction would produce wrong trips (e.g. a rider going Heredia→SJ would appear to ride past their destination, loop downtown, and return). We split it into two user-facing directions:

- **400p outbound (Heredia → SJ)** = stops 1–11 of the loop PDF (Terminal Heredia, Súper Fácil → Repuestos Gigante La Valencia, just past Puente Río Virilla).
- **400p inbound (SJ → Heredia)** = the separate 24-stop SJ→Heredia PDF, which is what Moovit shows riders as the return-direction stop pattern. The 21-stop loop-back portion of the outbound PDF is operator-internal and not modeled.

Knock-on effect: stops like "Pricesmart Heredia" (loop PDF stop 18) and "Walmart Ulloa" (stop 15) are NOT in 400p outbound. They appear on 400p **inbound** as `her_pricesmart_acera` and `her_walmart_los_lagos` (different physical curbs / nearby stops). The pre-existing `her_pricesmart` and `her_walmart` Stop rows are retained (referenced by `places.json`) but are not visited by any route. The planner needs the nearest-stop-on-route resolver (sprint 1 followup) to correctly serve queries like "PriceSmart → SJ".

## Stops — corridor seed (2026-05-16)

The corridor seed is built by `TransitPulseBackend/scripts/corridor/` from
three source files in `.sop/planning/transitpulse-m2/research/`:

| Source file | Purpose |
|---|---|
| `heredia-routes.md` | TS `export const` (named `.md`, read as text). Canonical stop sequences per route+direction, total trip duration. |
| `heredia-routes-raw.md` | Operator, headway, fare, schedule. Original Moovit PDF URLs. |
| `heredia-routes-lat-lng.md` | Hand-verified stop coordinates. **Source of truth for coords**; the build pipeline reads it but never writes it. |

The pipeline produces 166 unique canonical stops from 204 stop-instances
across 6 directions (400p out/in, 400u out/in, 400sd out/in). Stop IDs are
direction-agnostic slugs (e.g. `her_pricesmart`, `sj_term_rh`).

### Segment minutes (`route_stops.segment_minutes`)

Allocated by `scripts/corridor/generate_seed.py:build_route_stops_json` proportional to the haversine distance between consecutive stops, with iterative redistribution: gaps too small for ≥1 min get floored to 1 and the remaining budget is reallocated to bigger gaps until convergence.

The alternative (even split of `estimatedDurationMinutes` across `n-1` gaps) produced a planner artifact for SJ→Heredia: top option was "walk 10 min + ride 1 min via cemetery shortcut" because the long autopista gap got the same 1-min allocation as a 100m urban hop. With proportional allocation, the autopista gap gets 4–6 min (75 km/h) — realistic, so the shortcut still wins for SJ centro riders (it genuinely is faster than the 39-min Santo Domingo urban loop) but the times reflect actual geography.

Drift from operator-quoted duration is ≤ ±2 min for 400p and 400p, +5–9 min for 400sd/400u where many adjacent corner stops floor to 1 min. Acceptable for demo; tracked as M3 polish.

### Coord provenance (first-run snapshot, 2026-05-16)

After re-applying, all 166 stops report as `seed_existing` because they
were just written to `stops.json`. The breakdown below is the **originating
source** for each coord, preserved here because that's the auditable answer.

| Source | Count | Means |
|---|---:|---|
| `verified_md` | 7 | Hand-verified entry in `heredia-routes-lat-lng.md` (status=verified or status=candidate with conf=medium+). Highest trust. |
| `seed_existing` | 8 | Pre-corridor `stops.json` values (terminals, walmart, pricesmart, una, sj_irazu, sj_corobici, etc.). Manually placed during MLP and never re-verified. |
| `explicit_override` | 2 | `EXPLICIT_OVERRIDES` table in `scripts/corridor/merge.py` — used when Nominatim returns wrong results that need a hand-curated coord (`her_term_la400_pirro`, `her_term_aurora`). |
| `nominatim` | 22 | OSM Nominatim hit that passed the canton plausibility filter (display_name keyword check matches the id prefix). Low-confidence in Nominatim's importance scoring but spatially plausible. |
| `interpolated` | 127 | Linear interpolation between resolved anchors in the same direction sequence. **Not road-snapped.** Good enough for "show pin near where stop is" UX, NOT for precise nearest-stop boarding logic. |

### Known coord quality issues

- **Nominatim wrong-terminal hits.** Nominatim's top hit for "Terminal Heredia, Costa Rica" is a different building in San Isidro de Heredia (10.017, -84.056) — that's why we use `verified_md` (Súper Fácil at 9.9955, -84.1169) and `explicit_override` (Predio La 400 at Pirro). Don't rely on Nominatim for terminals.
- **Interpolated stops dominate (127 / 166 = 76%).** For the route detail screen this is fine (pins land along plausible bus path). For the planner's boarding-stop selection it is NOT — an interpolated coord may be 200–500 m off the real stop position, throwing off "is this stop near me" decisions. Sprint 1's nearest-stop resolver should de-weight stops with `source = interpolated`.
- **`her_pricesmart` and `her_walmart` are orphan stops** in `route_stops.json` (not visited by any of the 6 corridor directions, because PriceSmart Heredia and Walmart Ulloa sit on the loop-back portion of the 400p outbound PDF that we dropped). They're kept in `stops.json` because `places.json` references them; the planner should resolve "PriceSmart → SJ" by finding `her_pricesmart_acera` (400p inbound) as the nearest route-stop on a SJ-bound bus.

### How to improve coord coverage

1. **Add a verified entry to `heredia-routes-lat-lng.md`** for any stop you can place from Google Maps satellite or operator info. Re-run `python -m scripts.corridor.generate_seed --apply`. The pipeline is re-entrant — verified always wins.
2. **Add to `EXPLICIT_OVERRIDES`** in `scripts/corridor/merge.py` for stops where Nominatim returns a wrong location.
3. **Future: replace linear interpolation with OSRM polyline projection** (per `research/06-polyline-source.md`).

## Delay priors (2026-05-07)

All `delay_priors.n_observations = 0` because **no observation pipeline yet**.
Mean and std values are **hand-curated** based on the rough product
intuition documented in `.sop/planning/transitpulse-m2/research/02-prediction-algorithm.md`:

- Autopista routes (`400p`) have lower std — fewer urban traffic-light effects.
- Urban routes (`400sd`) have higher std — more variability, but lower
  late-night because traffic is light.
- Peak weekday hours (6–8, 16–18) have higher mean delay than off-peak.

Replace with measured values once M3 ships the observation pipeline.

## Known gaps / followups for the seed

1. **Nearest-stop-on-route resolver (sprint 1).** The planner currently picks
   the user's chosen stop verbatim and queries routes serving that stop. For
   stops like `her_pricesmart` (orphan after loop-split — no route visits
   it), this returns no options. The resolver should instead find the
   nearest stop on each route within walk radius (~800 m default), use that
   as boarding, and compute walk-to-stop minutes via haversine. Stops with
   `coord source = interpolated` should be de-weighted in the radius check.
2. **Real headway numbers.** Operators don't publish; current values are
   educated guesses. Verify with MRH and Transportes Unidos La 400 directly,
   or with a one-day stop-counting observation. 400u headway not yet
   modeled — uses 400p defaults.
3. **Real fare numbers.** ARESEP tariff page is JS-rendered. Try the CSV
   export endpoint directly, or contact ARESEP via email
   `ventanillaunica@aresep.go.cr`. 400u fare is placeholder.
4. **Polyline shape is anchor-only.** Road-snap via OSRM (per
   `research/06-polyline-source.md`) when ready. Visual sanity-check against
   satellite imagery before stakeholder demo. Same OSRM pass should also
   replace the linear interpolation used for 127 corridor stops.
5. **400sd is 24/7.** Schedule shape works (00:00–23:59) but `delay_priors`
   only seeds typical peak/off-peak hours (6–8, 16–18, 1, 3). Fill remaining
   168-hour grid via the YAML expander (`research/02-prediction-algorithm.md`)
   when the M2.3 prediction service lands.
6. **400u schedule/headway/delay_priors missing.** Route is added to
   `routes.json` with placeholder fare; `schedules.json` / `delay_priors.json`
   entries are not yet generated. Add before any 400u-related UX surfaces it.

## How to update this seed

### Corridor stops (400p / 400u / 400sd)

1. Update the appropriate research file under `.sop/planning/transitpulse-m2/research/`:
   - `heredia-routes.md` — stop sequence, trip duration.
   - `heredia-routes-raw.md` — operator, headway, fare, service hours.
   - `heredia-routes-lat-lng.md` — manually verified coordinates.
2. If you're adding a new raw stop name, also add an entry to `CANONICAL_IDS`
   in `TransitPulseBackend/scripts/corridor/dict_builder.py`. The slugifier
   will warn if it falls back to an auto-generated id.
3. Re-run the build pipeline:
   ```bash
   cd TransitPulseBackend
   .venv/bin/python -m scripts.corridor.geocode      # only if you added new landmark stops
   .venv/bin/python -m scripts.corridor.generate_seed --apply
   .venv/bin/python -m scripts.corridor.smoke        # static validation
   ```
4. Re-seed the DB: `flyctl ssh console -C "/var/task/bin/init-db.sh"` (or
   `python -m app.seed.load` locally with Postgres running).
5. Update this file — capture date and source for each change.

### Non-corridor stops / routes

1. Re-fetch Moovit pages (URLs above) — Moovit revises stop lists periodically.
2. Update `routes.json`, `route_stops.json`, `route_shapes.json`,
   `schedules.json`, `delay_priors.json` directly.
3. Re-seed.

## Why Moovit and not GTFS?

Costa Rica GTFS coverage is partial and stale — neither MRH nor Transportes
Unidos La 400 publish a usable feed. Moovit hand-curates from operator pages,
ARESEP, and field updates; their pages are the most current public source.
See `.sop/planning/transitpulse-m2/research/01-data-sourcing.md` for the
full alternatives analysis.

## License / attribution

- **Moovit** schedule data is reproduced from publicly browsable schedule
  pages. We re-key the underlying operator-published data; Moovit ToS
  restricts API use, not human reading of public schedule pages. Cited as the
  immediate source.
- **OpenStreetMap Nominatim** results are CC-BY-SA 2.0 — attribute "© OpenStreetMap
  contributors" wherever map tiles or geocoded coords are surfaced. Already
  in the frontend MapLibre attribution per the MLP map step.
- **ARESEP** route registry is public-domain government data; no attribution
  required, but cite the URL when used.
