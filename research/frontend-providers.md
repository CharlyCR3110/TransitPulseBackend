# Research — Frontend Provider Implementations

Source files (read directly):

- `src/data/providers/mock/planner-provider.ts`
- `src/data/providers/mock/stops-provider.ts`
- `src/data/providers/mock/alerts-provider.ts`
- `src/data/providers/mock/arrivals-provider.ts`
- `src/data/providers/mock/index.ts`
- `src/data/transit.ts` (the data the mocks read from)

The mock providers are the v1 API providers' **reference implementations** — semantics the backend must replicate to swap in cleanly.

---

## 1. Mock semantics, mapped to backend behavior

### `mockPlannerProvider`

| Provider method | Mock behavior | Backend equivalent |
|---|---|---|
| `searchTrips({ from, to, sort })` | Returns the static `TRIP_OPTIONS` list, sorted by `sort`. `from`/`to` are ignored. ~600ms simulated latency. | `GET /api/v1/planner/search?from&to&sort` — runs Q1 input resolution + Q2 live computation, then sorts by `sort`. Returns `TripOption[]`, possibly empty. |
| `getTripDetail(tripId)` | Looks up in `TRIP_OPTIONS`; returns `null` if not found. | `GET /api/v1/planner/trips/{tripId}` — `200` with `TripDetailDto`, `404` if no `trip_templates` row. |
| `startTrip(tripId)` | Returns `{ tripId, currentStepIndex: 0, steps, etaMinutes: trip.minutes, started: Date.now() }`. Returns `null` if trip not found. | `POST /api/v1/planner/trips/{tripId}/start` — Q3 lifecycle, Q4 anonymous addressing (returns `activeTripId` per Q14.C2), Q3 re-start idempotency. |
| `advanceStep(tripId, currentIndex)` | Computes `next = min(currentIndex + 1, steps.length - 1)`. Recomputes `etaMinutes` = sum of `step.minutes` from `next` to end. | `POST /api/v1/planner/trips/{tripId}/advance` body `{ currentStepIndex, activeTripId? }` — Q4 body shape. Auto-completes if `currentStepIndex == steps.length - 1` per Q3. |

Key behaviors to preserve:

- `etaMinutes` on `ActiveTripDto` is **remaining minutes from the current step to the end** — sum `step.minutes` from `currentStepIndex` onward. Not total trip duration.
- `advanceStep` clamps to `steps.length - 1` rather than overflowing — backend should do the same (and auto-transition status to `completed` when the clamp triggers, per Q3).
- The mock's `currentIndex` parameter is the **current** index the client thinks it is on; the result returns `currentIndex + 1` as the new `currentStepIndex`. Backend semantics should match: client sends "I am on step N," server returns "you are now on step N+1."

### `mockStopsProvider`

Reads from `NEARBY_STOPS` (3 stops). Backend equivalent: query `stops` table, optionally compute `dist` from query params (Q14.C4).

### `mockAlertsProvider`

Reads from `ALERTS`. Filtering by routes is just `routes.some(r => alert.routes.includes(r))`. Backend equivalent: `WHERE alerts.is_active AND EXISTS (jsonb array overlap)` or a normalized `alert_routes` join table — design choice in the design doc.

### `mockArrivalsProvider`

`getHomeArrivals()` returns `INITIAL_ARRIVALS` directly. `getArrivalsForStop(stopId)` returns the same list — the mock does not filter by `stopId`. Backend behavior:

- `GET /api/v1/arrivals/home` — likely returns the next-N arrivals across all "home" stops; for v1 we can treat "home" as a fixed seeded set or as "all live stops, top 6."
- `GET /api/v1/arrivals/stops/{stopId}` — must `404` if `stopId` is unknown (per spec §10) and otherwise compute upcoming arrivals from `arrival_schedules` (per Q8).

---

## 2. Provider exports

`src/data/providers/mock/index.ts` exports a single `mockProviders` object (or named exports per provider) that the frontend uses. The real-API equivalent will be a sibling `src/data/providers/api/` directory with the same exported shape.

Backend has no work here — this is a frontend wiring detail. But the design should note that the API provider implementations are a **separate task on the frontend side**, not backend scope.

---

## 3. What the providers do NOT do (gaps the backend must own)

- No reports submission. There's no `mockReportsProvider`. The backend's `POST /api/v1/reports` is greenfield from the frontend's perspective — the frontend needs a corresponding provider added.
- No auth. `register`/`login`/`me` flows have no mock provider counterparts. Same as reports — frontend will need a new provider.
- No JWT handling. Frontend has no token store yet. (Out of backend scope but flagged as a parallel frontend task.)

---

## 4. Latency notes

The mock injects `delay(600)` on `searchTrips` (simulating a slow backend) and `delay(0)` everywhere else. v1 backend should easily beat 600ms per the §14 perf budget.
