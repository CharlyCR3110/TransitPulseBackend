# Codebase Analysis for Crowdsourcing Feature

## 1. Report Model — Current State & Gaps

**File:** `app/models/report.py`

Current fields: `id`, `user_id` (FK, nullable), `route_id` (FK, nullable), `stop_id` (FK, nullable), `type` (str), `description` (text), `status` (str, default "new"), `source_ip` (INET), `created_at`.

**What needs to be added for crowdsourcing:**
- `direction` (str) — inferred from active trip; required for filtering reports by direction
- `active_trip_id` (FK → active_trips.id, nullable) — links the report to the trip context
- `expires_at` (datetime) — computed from `created_at` + TTL per type; extended by confirmations
- `confirm_count` (int, default 0) — number of confirmations received
- `deny_count` (int, default 0) — number of denials received

**What's fine as-is:**
- `route_id` FK already exists (route-scoped reports work)
- `stop_id` FK exists for optional stop context
- `user_id` nullable supports anonymous reports
- `source_ip` for rate limiting forensics
- `status` field supports the NEW → CONFIRMED → DISMISSED → RESOLVED workflow

**Note:** `route_id` and `stop_id` are currently optional (`nullable=True`). Since we're requiring active trip context, `route_id` will always be populated — but the column stays nullable for backward compat with any existing data.

---

## 2. Active Trip — Route & Direction Extraction

**File:** `app/models/active_trip.py`, `app/modules/planner/service.py`

Active trips store steps as JSON in `TripTemplate.steps`. Each bus step includes:
- `route` (str) — the route ID (e.g., "400p")
- `boardStopId`, `alightStopId` — boarding/alighting stops
- `fromEs`, `toEs` — origin/destination labels

**Direction is NOT stored explicitly** on `ActiveTripStep` or `TripTemplate`. However, direction can be inferred: `RouteStop` has `(route_id, direction, stop_order)`, so given a `route` + `boardStopId`, we can look up the direction from the seed cache.

**How to get route+direction from an active trip:**
1. Get `ActiveTrip` by `active_trip_id`
2. Find the current step (bus kind) via `current_step_index`
3. Extract `route` from the step's payload
4. Look up direction from `route_stops_by_route_dir` cache using the `boardStopId`

**Integration point for reporting:** When a user submits a report during an active trip, the backend can auto-populate `route_id` and `direction` from the current bus step — no user input needed.

---

## 3. Arrivals Service — Where Badges Would Surface

**File:** `app/modules/arrivals/service.py`, `app/modules/arrivals/schemas.py`

The arrivals endpoint already queries alerts to build a `route_status` map (`_route_status_map`). This maps `route_id → severity` ("ok" | "warn" | "bad") using active `Alert` + `AlertRoute` records.

**Key insight:** The `status` field on `ArrivalOut` already exists and is consumed by the frontend. The same pattern can surface crowd reports:

**Option A — Extend `_route_status_map`:** Query active (non-expired, confirmed) crowd reports alongside alerts. If a route has confirmed reports, set status to "warn" (or a new value).

**Option B — Add a separate field to `ArrivalOut`:** Add `crowdReports: list[CrowdReportSummary] | None` to the arrival schema. This carries richer info (type, count, description) without overloading the `status` field.

**Recommendation:** Option B is cleaner — the `status` field is alert-driven (operator-level), while crowd reports are a different signal. A new `crowdReports` field keeps them separate.

**Current `ArrivalOut` schema fields:** `id`, `route`, `kind`, `destEs`, `destEn`, `etaSec`, `status`, `occupancy`, `note_es`, `note_en`, `prediction`.

---

## 4. Report Submission — Current Endpoint

**File:** `app/modules/reports/router.py`, `app/modules/reports/service.py`, `app/modules/reports/schemas.py`

Current: `POST /api/v1/reports` — accepts `{ type, routeId?, stopId?, description }`, saves to DB, returns the created report.

**What needs to change for crowdsourcing:**
- Add `activeTripId` to `ReportSubmitIn` (required — active trip only)
- Backend validates the active trip exists and is in_progress
- Auto-populate `route_id`, `direction`, and optionally `stop_id` from the active trip's current step
- Compute `expires_at` based on report type TTL
- Rate limiting: check recent reports from same user/IP

**New endpoints needed:**
- `GET /api/v1/reports?routeId=X&direction=Y&status=active` — list active reports for a route
- `POST /api/v1/reports/{id}/confirm` — confirm a report (with optional detail text)
- `POST /api/v1/reports/{id}/deny` — deny a report

---

## 5. Confirmation/Denial — New Model Needed

No confirmation model exists. We need:

```
ReportReaction (new table)
  id: int (PK)
  report_id: int (FK → reports.id)
  user_id: str | None (FK → users.id, nullable)
  reaction: str ("confirm" | "deny")
  detail: str | None (optional context text)
  source_ip: str | None (INET)
  created_at: datetime
```

**Constraints:**
- One reaction per user per report (upsert — user can change their reaction)
- Anonymous reactions keyed by IP (one per IP per report)
- Each confirmation extends `Report.expires_at` by a configurable amount
- `Report.confirm_count` / `deny_count` are derived or denormalized

---

## 6. Alert System — Reuse Potential

**File:** `app/models/alert.py`, `app/modules/alerts/service.py`

Alerts are operator-level (manual or system-generated) with `severity`, `title_key`, `body_key`, and route associations via `AlertRoute`.

**Verdict:** Don't merge crowd reports into the Alert model. They serve different purposes:
- Alerts = operator/system-level, long-lived, i18n keys
- Reports = user-generated, short-lived, free text

However, the `_route_status_map` pattern in `ArrivalsService` is a good template for building a `_route_crowd_reports_map`.

---

## 7. TTL Configuration — Report Type Defaults

Based on requirements (hybrid expiry) and the external research reference, suggested TTLs:

| Report Type    | Default TTL | Confirmation Extension |
|----------------|-------------|----------------------|
| DELAY          | 30 min      | +15 min per confirm  |
| OVERCROWDING   | 20 min      | +10 min              |
| BREAKDOWN      | 60 min      | +30 min              |
| ACCIDENT       | 120 min     | +30 min              |
| ROUTE_CHANGE   | 120 min     | +60 min              |
| SAFETY         | 60 min      | +30 min              |
| OTHER          | 30 min      | +15 min              |

These would live as a config dict in the service or settings, not in the DB.

---

## 8. Rate Limiting

No rate limiting infrastructure exists. FastAPI options without Redis:
- **In-memory dict** with IP/user → timestamp list. Simple, but resets on restart and doesn't scale across workers.
- **DB-based**: Query `Report.created_at` for the user/IP in the last hour. Slightly slower but persistent and accurate.
- **SlowAPI** library: FastAPI middleware, uses in-memory by default, supports Redis backend later.

**Recommendation for MVP:** DB-based check — `SELECT COUNT(*) FROM reports WHERE (user_id = :uid OR source_ip = :ip) AND created_at > now() - interval '1 hour'`. If count >= 5, reject. Simple, no new dependencies, works across workers.

---

## 9. Dedup Logic

Same type + same route + same direction within a time window (e.g., 10 min) → don't create a new report, instead auto-confirm the existing one.

Query: `SELECT id FROM reports WHERE route_id = :rid AND direction = :dir AND type = :type AND expires_at > now() ORDER BY created_at DESC LIMIT 1`.

If found → create a `ReportReaction(confirm)` on that report instead of a new report.

---

## 10. Migration Infrastructure

**Dir:** `migrations/` with Alembic (`env.py`, `script.py.mako`, empty `versions/`).

Alembic is set up but the versions directory is empty — migrations may be auto-generated or tables created via `Base.metadata.create_all()`. New columns and tables can be added via Alembic migrations.

---

## 11. Frontend Integration Points

**Repo:** `/home/charlygg/workspace/TransitPulseWebsite/` (separate Next.js 16 app)

The frontend uses OpenAPI codegen (`gen:api` script). Adding new fields to `ArrivalOut` or new endpoints will auto-generate TypeScript types after re-running codegen.

Key integration:
- Arrival cards already render `status` — adding a `crowdReports` field would let the frontend show badges
- Active trip view already has step progression — adding a "Report" button on bus steps is the natural trigger
- React Query handles data fetching — polling for fresh report data fits naturally
