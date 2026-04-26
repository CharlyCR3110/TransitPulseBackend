# Research — Frontend Contracts (canonical wire shapes)

Source files (read directly from `TransitPulseWebsite/`):

- `src/data/contracts/planner.ts`
- `src/data/contracts/stops.ts`
- `src/data/contracts/alerts.ts`
- `src/data/contracts/arrivals.ts`
- `src/types/transit.ts` (the underlying type definitions)
- `src/data/transit.ts` (mock data and the `I18N` translation table)
- `src/data/providers/mock/*.ts` (mock provider implementations)

Per spec §10, these contract files are canonical for response shapes. The backend's Pydantic schemas must align with these without requiring the frontend to write adapter logic.

---

## 1. The canonical types

### `Stop` (used by `getStop`, `getAllStops`, and embedded in `StopDetailDto`)

```ts
interface Stop {
  id: string;
  nameKey: string;     // i18n LOOKUP KEY, not text — e.g. "stop_1"
  addrKey: string;     // i18n LOOKUP KEY, not text — e.g. "stop_1_addr"
  dist: number;        // distance in meters; reference point unspecified
  live: boolean;
  routes: string[];    // route IDs serving this stop
}
```

> **Conflict with spec §11.2:** the spec lists `stops.name` and `stops.address` as text columns; the wire contract expects i18n lookup keys, with the actual translated strings living in the frontend's `I18N.es` / `I18N.en` tables in `src/data/transit.ts`.

### `StopDetailDto`

```ts
interface StopDetailDto {
  stop: Stop;
  arrivals: Arrival[];
  updatedAt: number;   // epoch ms
}
```

### `Arrival`

```ts
interface Arrival {
  id: string;
  route: string;
  kind: 'bus' | 'train';
  destEs: string;      // INLINE bilingual text
  destEn: string;
  etaSec: number;      // ETA in seconds
  status: 'on-time' | 'delayed' | 'disrupted' | 'unknown' | 'ok' | 'warn' | 'bad';
  occupancy: number;   // 0–4 scale (low → packed)
  note_es?: string;
  note_en?: string;
}
```

> **Conflict with Q5:** `Arrival` has inline bilingual fields (`destEs`/`destEn`, `note_es`/`note_en`). Q5 said only alerts are bilingual at the data layer; arrivals must be too if we honor the contract.

### `Alert`

```ts
interface Alert {
  id: string;
  severity: 'bad' | 'warn' | 'ok';
  titleKey: string;    // i18n LOOKUP KEY — e.g. "alert_1_title"
  bodyKey: string;     // i18n LOOKUP KEY — e.g. "alert_1_body"
  time: string;        // human-readable relative time, e.g. "12 min", "2 h"
  routes: string[];
}
```

> **Conflict with spec §11.2:** the spec lists `title_es / title_en / body_es / body_en` as text columns; the wire contract expects i18n lookup keys.
>
> **Note on `time`:** it's a string, not an ISO timestamp. The mock data uses pre-baked human strings. Backend either ships an ISO datetime and lets the frontend format, or backend formats the relative string. Open question.

### `TripStep` (discriminated union)

```ts
type TripStep =
  | { kind: 'walk';     minutes: number; toEs: string; toEn: string; time: string }
  | { kind: 'bus';      route: string; minutes: number; fromEs: string; fromEn: string; toEs: string; toEn: string; time: string; occ: number; stops: number }
  | { kind: 'transfer'; minutes: number; toEs: string; toEn: string; time: string };
```

> **Conflict with Q5:** every step variant has inline bilingual `_es`/`_en` text fields. Step descriptions must be bilingual too.

### `TripOption` and `TripDetailDto`

```ts
interface TripOption {
  id: string;
  tag: string;          // a label like "fastest" / "cheapest" / "fewest" — derived per search
  minutes: number;
  price: number;
  transfers: number;
  walkMin: number;
  leaveIn: number;      // minutes until departure
  confidence: number;   // 0–1
  occupancy: number;    // 0–4 scale
  steps: TripStep[];
}

interface TripDetailDto {
  id: string;
  minutes: number;
  price: number;
  transfers: number;
  walkMin: number;
  leaveIn: number;
  confidence: number;
  occupancy: number;
  steps: TripStep[];
}
```

> **Note:** in the mock implementation, `getTripDetail` returns the same row that `searchTrips` returns, minus the `tag` field. So `TripDetailDto` is structurally `TripOption` without `tag`. Backend can persist the `tripId` plus its computed metrics and steps; `tag` is set per-search based on the requested sort mode.
>
> **Note:** `confidence` and `occupancy` in `TripOption`/`TripDetailDto` are computed/synthesized — not in spec §11.2 data model. Backend has to produce them somehow (defaulted heuristics in v1 are fine).

### `ActiveTripDto`

```ts
interface ActiveTripDto {
  tripId: string;
  currentStepIndex: number;
  steps: TripStep[];
  etaMinutes: number;     // remaining minutes from current step to end
  started: number;        // epoch ms
}
```

> **Conflict with Q4:** Q4's answer extended the `/advance` body with `activeTripId`, but the canonical `ActiveTripDto` returned by `/start` has no `activeTripId` field — only `tripId`. If we honor the contract literally, anonymous clients have no token to echo back.
>
> Three ways to reconcile:
> 1. **Add `activeTripId` to the DTO** (mild contract extension; frontend ignores it if not needed).
> 2. **Use `tripId` itself as the addressing key** for anonymous clients — e.g., the backend issues a per-anonymous-client opaque ID that gets stuffed into the response `tripId` field, treating "trip template ID" and "active trip ID" as the same string from the client's POV. Hacky.
> 3. **Disallow anonymous active trips** — forces auth on `/start`; cleanest but contradicts the spec's "auth optional in the first implementation."
>
> Recommendation: option 1 (extend the DTO). Q4 needs reopening to confirm.

### Provider interfaces (the actual API the frontend calls)

```ts
interface PlannerProvider {
  searchTrips(input: PlannerSearchInput): Promise<TripOption[]>;
  getTripDetail(tripId: string): Promise<TripDetailDto | null>;
  startTrip(tripId: string): Promise<ActiveTripDto | null>;
  advanceStep(tripId: string, currentIndex: number): Promise<ActiveTripDto | null>;
}

interface StopsProvider {
  getStop(stopId: string): Promise<StopDetailDto | null>;
  getAllStops(): Promise<Stop[]>;
}

interface AlertsProvider {
  getAlerts(): Promise<Alert[]>;
  getAlertsForRoutes(routes: string[]): Promise<Alert[]>;
}

interface ArrivalsProvider {
  getHomeArrivals(): Promise<Arrival[]>;
  getArrivalsForStop(stopId: string): Promise<Arrival[]>;
}
```

> **Note:** `null` returns map to `404`s on the wire (per spec §10 "invalid IDs must return 404").
>
> **Note:** `advanceStep(tripId, currentIndex)` — the mock takes only `(tripId, currentIndex)`. The mock would not pass an `activeTripId`. If we extend the body per Q4, the frontend's API provider implementation must add it; the contract interface itself stays the same.

---

## 2. Conflicts that need user resolution

### C1. i18n strategy mismatch (reopens Q5)

The spec says alerts store `title_es / title_en / body_es / body_en` (inline bilingual text). The contract expects `titleKey / bodyKey` (i18n lookup keys, with text in a frontend `I18N` table).

The contract additionally requires inline bilingual text on `Arrival` (`destEs/destEn`, `note_es/note_en`) and on every `TripStep` variant (`toEs/toEn`, `fromEs/fromEn`).

So the frontend uses **two i18n patterns simultaneously**:

- **Lookup keys** for `Stop` (`nameKey`, `addrKey`) and `Alert` (`titleKey`, `bodyKey`).
- **Inline `_es/_en` pairs** for `Arrival` and `TripStep` variants.

This contradicts Q5's "alerts only are bilingual; everything else single-language Spanish at the data layer." Q5 needs revisiting with one of these resolutions:

- **R1.** Honor the contract literally. Stops and alerts ship lookup keys; arrivals and trip steps ship inline bilingual text. The backend stores keys for stops/alerts and inline `_es/_en` text for arrival destinations and step descriptions. The frontend's `I18N` table is a shared vocabulary — adding a stop or alert requires backend seed update + frontend translation entry.
- **R2.** Push toward inline bilingual everywhere. Replace the contract's `nameKey`/`addrKey` and `titleKey`/`bodyKey` with `nameEs`/`nameEn`/`addrEs`/`addrEn` and `titleEs`/`titleEn`/`bodyEs`/`bodyEn`. Frontend must update its provider implementations and stop reading from `I18N` for these entities. Self-contained data flow, more work on the frontend.
- **R3.** Push toward keys everywhere. Backend ships keys for everything, including arrivals (`destKey`, `noteKey`) and trip steps (`toKey`, `fromKey`). Forces the frontend's `I18N` table to also know every dynamic stop/destination/place name — impractical for trip steps where the place set is the union of all stops × all neighborhoods.

R1 is the path of least frontend churn. R2 is cleanest if anyone is open to a small frontend refactor. R3 is impractical.

### C2. `ActiveTripDto` lacks `activeTripId` (reopens Q4)

Q4's answer added `activeTripId` to the `/advance` request body. But the contract's `ActiveTripDto` returned by `/start` has no `activeTripId` field — only `tripId`.

For authenticated users this is fine: the backend resolves "your in-progress trip for this trip template" from `(user_id, tripId)`. For anonymous users there's no session, so the client cannot reference a specific active trip later.

Resolutions:

- **R1.** Extend the DTO with an optional `activeTripId` field. Smallest contract extension; frontend ignores it when authenticated. Recommended.
- **R2.** Use a header (`X-Active-Trip-Id`) — keeps the DTO clean but moves state into HTTP metadata. Valid alternative.
- **R3.** Disallow anonymous active trips — overrides Q3.

### C3. `Alert.time` is a string

The contract types `time: string` and the mock data stores pre-baked human-readable relative strings (`"12 min"`, `"2 h"`). The spec column is `emitted_at` (presumably a timestamp).

Resolutions:

- **R1.** Backend ships ISO 8601 timestamp; rename the wire field to `emittedAt` (mild contract extension, frontend formats). Cleanest.
- **R2.** Backend ships the human relative string by formatting `emitted_at` server-side (locale-sensitive, brittle).
- **R3.** Backend ships both — `emittedAt: string` (ISO) and `time: string` (formatted).

R1 is recommended; the mock's `time` string is clearly a placeholder.

### C4. Stop `dist` field

`Stop.dist` is a number (meters?), but its reference point is unspecified. The mock hard-codes values. Two paths:

- **R1.** Backend always returns `dist: 0` in v1 (no geolocation). Documented gap.
- **R2.** `GET /api/v1/stops` accepts optional `?lat=&lng=` query params (already flagged in spec §9.2 as a future addition); when provided, `dist` is computed via Haversine on `stops.lat/lng`; otherwise 0.

R2 is barely more work than R1 since `stops.lat/lng` are already in the spec data model, and unlocks the "near me" UX for free.

### C5. Confidence / occupancy on `TripOption`

These are not in the spec data model (`§11.2` `trip_templates` doesn't define them). They're computed metrics. v1 should populate them with deterministic heuristics:

- `confidence` = `1.0 - (transfers * 0.05) - (walkMin / 60.0)` clamped to `[0, 1]`.
- `occupancy` = max occupancy across the trip's bus steps (`occ` field), or `0` if no bus steps.

Documented as v1 placeholder logic.

---

## 3. Translation key inventory (snapshot)

The frontend's `I18N` table in `src/data/transit.ts` already defines these keys for stops and alerts:

- Stops: `stop_1`, `stop_1_addr`, `stop_2`, `stop_2_addr`, `stop_3`, `stop_3_addr`.
- Alerts: `alert_1_title`, `alert_1_body`, `alert_2_title`, `alert_2_body`, `alert_3_title`, `alert_3_body`, `alert_4_title`, `alert_4_body`.

Under R1 (Q5 resolution C1.R1), the v1 seed data uses these exact keys for the seeded entities so the existing `I18N` table works without changes.

If the seed grows beyond these examples, every new stop/alert requires both a backend seed entry and a matching `I18N` entry.

---

## 4. Action items for design

Once Q4 and Q5 are resolved (see §2 above):

- Pydantic schemas for stops, alerts, arrivals, trips mirror the contract types — with field naming consistent with the chosen i18n resolution.
- DB columns store either keys or `_es/_en` text per resolution.
- The trip option `tag` field is computed at search time from the requested `sort` parameter.
- `confidence` and `occupancy` are computed via the heuristics above.
- The mock providers in `src/data/providers/mock/` are the reference implementations the API providers must match.
