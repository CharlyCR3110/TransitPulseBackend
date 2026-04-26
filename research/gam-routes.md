# Research — GAM Routes & Operators (seed reference)

Source: user-provided in `extra-information.md` (item 1). The user anchored on official CTP / open-data and operator pages, then used Moovit-style schedule pages for headway ballparks. CTP maintains an open-data "Rutas Regulares" dashboard (last updated Sept. 18, 2025) but no public official GTFS feed with `route_long_name` was located.

The following table is reproduced verbatim from the user's research and is the source of truth for the v1 seed.

## Operator / route table

| Operator | Route / route long name | Corridor | Headway ballpark |
|---|---|---|---|
| **Transportes Unidos La 400 S.A.** | **SAN JOSÉ – HEREDIA POR LA URUCA – 400** | San José terminal near Tienda Maracay ↔ Heredia | Weekdays ~5–10 min; Saturday 6–10 min; Sunday 8–14 min. |
| **Microbuses Rápidos Heredianos S.A.** | **SAN JOSÉ – HEREDIA POR SANTO DOMINGO** / **SAN JOSÉ – HEREDIA POR TIBÁS Y SANTO DOMINGO – 400 A (MB-BS)** | San José ↔ Tibás/Santo Domingo ↔ Heredia | 24-hr; weekdays ~3–5 min, Saturday 4–8 min, Sunday 4–10 min. |
| **TUASA / Transportes Unidos Alajuelenses S.A.** | **HEREDIA – SAN JOSÉ POR PISTA** | Heredia ↔ San José via pista | Daily 05:00–22:00; weekdays 4–5 min, Saturday 5 min, Sunday 10 min. |
| **TUASA / Transportes Unidos Alajuelenses S.A.** | **ALAJUELA – HEREDIA – SAN JOSÉ** | Alajuela ↔ Heredia ↔ San José | Weekday 6 min peak / 8 min midday / 10 min evening; weekends 8–12 min. |
| **Transportes Unidos La 400 S.A.** | **SAN JOSÉ – LA AURORA POR LA PISTA – 400** | San José ↔ La Aurora / Heredia sector via pista | Weekdays 5–20 min, Saturday 10–20 min, Sunday 15–25 min. |
| **Transportes Unidos La 400 S.A.** | **SAN JOSÉ – LA MILPA – GUARARÍ POR LA URUCA – 400** | San José ↔ La Uruca ↔ La Milpa / Guararí | Weekdays 12–20 min, Saturday 16–20 min, Sunday 20–24 min. |
| **Transportes Unidos La 400 S.A.** | **SAN JOSÉ – LA MILPA – GUARARÍ POR PISTA – 400** | San José ↔ Guararí / Hospital San Vicente de Paúl via pista | ~1 hour; weekdays 58–67 min, Saturday 53–60 min, Sunday 48–72 min. |
| **Transportes Rutas 407 y 409 S.A.** | **SAN JOSÉ – SAN RAFAEL DE HEREDIA** | San José ↔ San Rafael de Heredia | Weekdays 21–60 min; weekends ~60 min. |
| **Transportes Arnoldo Ocampo S.A.** | **SAN JOSÉ – SAN ISIDRO DE HEREDIA X PISTA – 434–436** | San José ↔ San Isidro de Heredia | Weekdays 20–40 min, Saturday 20–49 min, Sunday 28–60 min. |
| **Transportes Unidos La 400 S.A.** | **HEREDIA – CENADA – LAGUNILLA – 402** | Heredia local feeder | Weekdays 20 min, Saturday 20–25 min, Sunday 30–60 min. (Heredia-side feeder, not a San José trunk.) |

## Picking the v1 seed (5 routes, per Q8)

Given the Q8 cap of ~5 routes / ~30 stops, we want a tight, demoable subset that exercises all the planner code paths (direct, single-transfer, low-frequency edge case). Suggested picks:

1. **400 — Transportes Unidos La 400 S.A. — SAN JOSÉ – HEREDIA POR LA URUCA**. High-frequency trunk; Q8 base case for "dense schedule, fast ETA."
2. **400A — Microbuses Rápidos Heredianos — SAN JOSÉ – HEREDIA POR TIBÁS Y SANTO DOMINGO**. 24-hr coverage; covers the night-service edge case for `arrival_schedules`.
3. **200 — TUASA — HEREDIA – SAN JOSÉ POR PISTA**. Different operator; alternate corridor between the same two endpoints — useful for the "fastest vs cheapest" sort comparison.
4. **407 — Transportes Rutas 407 y 409 — SAN JOSÉ – SAN RAFAEL DE HEREDIA**. Low-frequency route; tests the "long ETA, sparse schedule" rendering and forces a real headway ballpark in seed data.
5. **402 — Transportes Unidos La 400 — HEREDIA – CENADA – LAGUNILLA**. Heredia-local feeder; gives the planner a one-transfer scenario (e.g., "from Lagunilla to San José" requires 402 → 400).

## Stop seed (~30 stops)

Tentative shape, to be finalized in seed authoring:

- **San José**: Tienda Maracay terminal, Av. 2, Mercado Central, La Uruca, Hospital México area.
- **Heredia centro**: Mercedes Norte, terminal de buses Heredia.
- **Tibás / Santo Domingo**: 400A corridor stops.
- **Lagunilla / CENADA / La Aurora**: feeder stops.
- **San Rafael de Heredia**: terminus + 1–2 intermediate stops.
- **San Isidro de Heredia**: skipped from v1 seed unless we promote 434–436 over 407.

Detail finalized in implementation plan (seed authoring step).

## Operational caveat (from user's note)

The user explicitly flagged: *"For a dataset, I would label the operational status carefully rather than treating it as cleanly resolved."* — meaning headways and operator-route mappings are best-effort from public schedule pages, not definitive. The v1 seed is **plausible synthetic data**, not a claim of GTFS accuracy. The design doc should reflect this in a "seed disclaimer" note.

## Sources

User-cited in `extra-information.md`:

- Consejo de Transporte Público (CTP) — Rutas Regulares dashboard
- Moovit schedule pages (per route)
- Grupo TUASA official page (TUASA-operated headways)
