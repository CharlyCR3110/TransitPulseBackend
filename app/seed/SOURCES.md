# Seed data provenance

> Last updated: 2026-05-07.
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
| Stops (full list, 32 outbound) | [Moovit PDF](https://appassets.mvtdev.com/map/188/l/2967/48315295.pdf) | 2026-05-07 | Full list preserved in `.sop/planning/transitpulse-m2/research/heredia-routes-raw.md` |
| Stops (subset of 8 in seed) | Same PDF + OSM Nominatim | 2026-05-07 | Anchor stops only — terminals + major landmarks |
| Trip duration | Moovit PDF | 2026-05-07 | 32 min outbound (Heredia → SJ) |
| Hours of operation | Moovit PDF | 2026-05-07 | Daily 05:00 – 22:00 |
| Headway | **Estimated** | 2026-05-07 | Operator does not publish; used 12 / 15 / 20 min for weekday/sat/sun. Verify with operator before stakeholder demo. |
| Fare (CRC) | **Placeholder** | 2026-05-07 | 750 CRC — peer-route reference for ~14 km GAM corridor. ARESEP tariff page is JS-rendered; need separate fetch or operator confirmation. |
| Polyline shape | **Anchor-only** | 2026-05-07 | LineString through 8 anchor stops, not road-snapped. M3 should run OSRM with bus-friendly profile. |

### `400sd` — San José ↔ Heredia POR SANTO DOMINGO — urban corridor (24/7)

| Field | Source | Captured | Notes |
|---|---|---|---|
| Route name | Moovit | 2026-05-07 | "SAN JOSÉ - HEREDIA POR SANTO DOMINGO" |
| Operator | Moovit | 2026-05-07 | Microbuses Rápidos Heredianos S.A. (MRH) |
| Stops (full list, 40 outbound) | [Moovit PDF](https://appassets.mvtdev.com/map/188/l/2967/48315296.pdf) | 2026-05-07 | Full list preserved in research doc |
| Stops (subset of 6 in seed) | Same PDF + OSM Nominatim | 2026-05-07 | Anchor stops only |
| Trip duration | Moovit PDF | 2026-05-07 | 34 min outbound (SJ → Heredia) |
| Hours of operation | Moovit PDF | 2026-05-07 | **24 horas** — service runs around the clock |
| Headway | **Estimated** | 2026-05-07 | Operator does not publish; used 10 / 15 / 20 min for weekday/sat/sun. |
| Fare (CRC) | **Placeholder** | 2026-05-07 | 720 CRC — placeholder; ARESEP MRH tariff page needed for verification. |
| Polyline shape | **Anchor-only** | 2026-05-07 | LineString through 6 anchor stops, not road-snapped. |

## Stops (new for M2)

### Geocoded via OpenStreetMap Nominatim (2026-05-07)

| ID | Stop | Source | Lat | Lng |
|---|---|---|---:|---:|
| `her_estadio` | Estadio Eladio Rosabal Cordero | Nominatim direct hit | 9.9995 | -84.1230 |
| `her_pricesmart` | PriceSmart Heredia | Nominatim direct hit | 9.9829 | -84.1076 |
| `sj_term_cocacola` | Terminal Coca Cola, San José | Nominatim "Terminal Coca Cola" | 9.9363 | -84.0861 |
| `sj_tibas_cinco` | Cinco Esquinas de Tibás | Nominatim village query | 9.9474 | -84.0823 |
| `sd_plaza` | Plaza Santo Domingo | Nominatim mall query | 9.9718 | -84.0881 |

### Approximated coordinates (2026-05-07)

Nominatim returned empty results or wrong locations; coords below are based on
well-known geography of the GAM and OSM map sanity-check. Verify before any
production deployment.

| ID | Stop | Lat | Lng | Reason |
|---|---|---:|---:|---|
| `her_term_mc` | Terminal Heredia · Mercado Central | 9.9989 | -84.1165 | Heredia centro reference; near Mercado Central building |
| `her_term_braulio` | Terminal Heredia · Esc. Braulio Morales | 9.9985 | -84.1158 | Same Heredia centro cluster as Mercado Central terminal |
| `her_term_400` | Terminal Heredia · Predio La 400 (Pirro) | 10.0078 | -84.1115 | Pirro neighborhood, north of Heredia centro |
| `her_una` | Universidad Nacional · UNA | 10.0024 | -84.1099 | Well-known UNA Heredia campus location |
| `her_walmart` | Walmart Ulloa | 9.9729 | -84.1453 | Nominatim returned nearby Maxi Palí (10 KM-related); used OSM map sanity for actual Walmart big-box |
| `her_cenada` | Terminal Cenada | 9.9866 | -84.1248 | Barreal de Heredia; Nominatim's `-84.1502` looked too far west, used corrected value |
| `pte_virilla` | Puente Río Virilla · Autopista | 9.9676 | -84.1109 | Vuelta del Virilla on Autopista General Cañas |
| `sj_irazu` | Hotel Irazú | 9.9494 | -84.1098 | Well-known landmark on Autopista General Cañas |
| `sj_corobici` | Hotel Crowne Plaza Corobicí | 9.9412 | -84.1019 | La Sabana, San José |
| `sj_term_rh` | Terminal Rápidos Heredianos · Tournón | 9.9420 | -84.0758 | Tournón neighborhood, NE of San José centro |

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

1. **Full stop list (47-stop and 40-stop) not in seed.** Only the 8 + 6 anchor
   subset is loaded. Adding the rest requires geocoding ~70 minor stops; not
   blocking for M2 demo. File as M2.2 followup.
2. **Real headway numbers.** Operators don't publish; current values are
   educated guesses. Verify with MRH and Transportes Unidos La 400 directly,
   or with a one-day stop-counting observation.
3. **Real fare numbers.** ARESEP tariff page is JS-rendered. Try the CSV
   export endpoint directly, or contact ARESEP via email
   `ventanillaunica@aresep.go.cr`.
4. **Inbound directions.** `route_stops` schema has no `direction` column —
   only outbound is modeled today. Schema add is small (one column, one
   migration); should land before M2.5 (frontend route detail screen) so
   users can toggle direction.
5. **Polyline shape is anchor-only.** Road-snap via OSRM (per
   `research/06-polyline-source.md`) when ready. Visual sanity-check against
   satellite imagery before stakeholder demo.
6. **400sd is 24/7.** Schedule shape works (00:00–23:59) but `delay_priors`
   only seeds typical peak/off-peak hours (6–8, 16–18, 1, 3). Fill remaining
   168-hour grid via the YAML expander (`research/02-prediction-algorithm.md`)
   when the M2.3 prediction service lands.

## How to update this seed

1. Re-fetch Moovit pages (URLs above) — Moovit revises stop lists periodically.
2. Diff against the lists in `.sop/planning/transitpulse-m2/research/heredia-routes-raw.md`.
3. Update `routes.json`, `route_stops.json`, `route_shapes.json`,
   `schedules.json`, `delay_priors.json` as needed.
4. Re-seed: `flyctl ssh console -C "/var/task/bin/init-db.sh"` (or
   `python -m app.seed.load` locally).
5. Update this file — capture date and source for each change.

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
