# Crowdsourcing Feature — Implementation Plan

## Checklist

- [x] Step 1: Database migration — extend Report model + create ReportReaction table
- [x] Step 2: TTL config + report type validation
- [x] Step 3: Direction inference from active trip
- [x] Step 4: Rewrite POST /reports with active trip context + dedup + rate limiting
- [x] Step 5: GET /reports endpoint — list active reports by route+direction
- [x] Step 6: POST /reports/{id}/confirm — confirmation with detail + expiry extension
- [x] Step 7: POST /reports/{id}/deny — denial + auto-dismiss logic
- [x] Step 8: Arrivals integration — crowdReports field on ArrivalOut
- [x] Step 9: Backend deploy — migrate Neon + deploy to Fly + smoke test
- [x] Step 10: Frontend — report submission from active trip view
- [x] Step 11: Frontend — crowd report badges on arrival/trip cards
- [x] Step 12: Frontend — confirm/deny UI on report detail
- [x] Step 13: Frontend deploy — deploy to Vercel + end-to-end smoke test

### Phase 2: Crowd-Adjusted Predictions

- [x] Step 14: Backend — crowd delay adjustment config + logic in arrivals service
- [x] Step 15: Backend — occupancy boost from OVERCROWDING reports
- [x] Step 16: Schema — add `crowdAdjusted` flag to ArrivalPrediction
- [x] Step 17: Backend deploy — deploy to Fly + smoke test
- [x] Step 18: Frontend — crowd-adjusted ETA indicator on arrival badges
- [x] Step 19: Frontend deploy — deploy to Vercel + e2e verify

---

## Step 1: Database migration — extend Report model + create ReportReaction table

**Objective:** Add the new columns to `reports` and create the `report_reactions` table so all subsequent steps have the schema they need.

**Implementation guidance:**
- Add columns to `Report` model in `app/models/report.py`: `direction` (String(32), nullable), `active_trip_id` (FK → active_trips.id, nullable), `expires_at` (DateTime(timezone=True), nullable), `confirm_count` (Integer, default 0), `deny_count` (Integer, default 0)
- Create `ReportReaction` model in `app/models/report_reaction.py`: `id` (PK), `report_id` (FK → reports.id), `user_id` (FK → users.id, nullable), `reaction` (String(8)), `detail` (Text, nullable), `source_ip` (INET, nullable), `created_at`
- Add composite index on `reports`: `(route_id, direction, expires_at)` for active report queries
- Add unique constraint on `report_reactions`: `(report_id, user_id)` for authenticated users
- Add index on `report_reactions`: `(report_id, reaction)`
- Generate Alembic migration and run it against the local DB

**Test requirements:**
- Migration applies cleanly (upgrade + downgrade)
- Existing report rows unaffected (new columns are nullable/have defaults)

**Demo:** Run `alembic upgrade head`, verify new columns in `\d reports` and new `report_reactions` table in psql.

---

## Step 2: TTL config + report type validation

**Objective:** Centralize report type constants, TTL defaults, and confirmation extension values so the submission and confirmation logic can reference them.

**Implementation guidance:**
- Create `app/modules/reports/config.py` with:
  - `ReportType` enum (DELAY, BREAKDOWN, ACCIDENT, OVERCROWDING, ROUTE_CHANGE, SAFETY, OTHER)
  - `REPORT_TTL_MINUTES` dict mapping each type to its default TTL
  - `REPORT_CONFIRM_EXTENSION_MINUTES` dict mapping each type to its extension per confirmation
  - `CONFIRM_THRESHOLD = 2`
  - `DISMISS_MARGIN = 2`
  - `RATE_LIMIT_PER_HOUR = 5`
  - `DEDUP_WINDOW_MINUTES = 10`
- Update `ReportSubmitIn` schema to validate `type` against the `ReportType` enum
- Add a helper function `compute_expires_at(report_type: str, base: datetime) -> datetime` that returns `base + timedelta(minutes=TTL)`

**Test requirements:**
- `compute_expires_at` returns correct datetime for each report type
- Invalid report type in `ReportSubmitIn` raises 422

**Integrates with:** Step 1 (model), Step 4 (submission logic)

**Demo:** Submit a report with type `"INVALID"` via the API and confirm a 422 response. Unit test TTL computation for each type.

---

## Step 3: Direction inference from active trip

**Objective:** Build a utility that, given an `active_trip_id`, extracts the current route and direction from the trip's bus step using the seed cache.

**Implementation guidance:**
- Add method to `ReportsService` (or a shared helper): `_infer_route_context(active_trip_id: str, session: Session) -> dict` returning `{ route_id, direction, stop_id }` or raising `NotFoundError`
- Logic:
  1. Query `ActiveTrip` by `active_trip_id` where status = `in_progress`
  2. Query `ActiveTripStep` for the current step (or the most recent bus step at or before `current_step_index`)
  3. Extract `route` and `boardStopId` from the step's payload
  4. Look up `route_stops_by_route_dir` in seed cache: find the `(route_id, direction)` key where `boardStopId` appears in the stops list
  5. Return `{ route_id, direction, stop_id: boardStopId }`
- Handle edge cases: trip not found, trip not in_progress, current step is a walk (scan for nearest bus step)

**Test requirements:**
- Given an active trip on 400p Heredia→SJ, infer route_id="400p" and correct direction
- Trip not found → 404
- Trip completed → 404
- Current step is walk → falls back to nearest bus step

**Integrates with:** Step 1 (ActiveTrip model), Step 4 (submission uses this)

**Demo:** Start a trip via `POST /planner/trips/{id}/start`, call the inference function, print the extracted route+direction.

---

## Step 4: Rewrite POST /reports with active trip context + dedup + rate limiting

**Objective:** Transform the existing report submission endpoint to require active trip context, auto-populate route/direction, apply dedup and rate limiting.

**Implementation guidance:**
- Update `ReportSubmitIn` schema: add `activeTripId` (required str), remove `routeId` and `stopId` (now auto-inferred), make `description` optional (default empty string, max 500 chars)
- Update `ReportsService.submit()`:
  1. Call `_infer_route_context(activeTripId)` to get route_id, direction, stop_id
  2. **Rate limit check:** `SELECT COUNT(*) FROM reports WHERE (user_id = :uid OR source_ip = :ip) AND created_at > now() - interval '1 hour'`. If >= `RATE_LIMIT_PER_HOUR`, raise 429
  3. **Dedup check:** `SELECT * FROM reports WHERE route_id = :rid AND direction = :dir AND type = :type AND expires_at > now() AND created_at > now() - DEDUP_WINDOW ORDER BY created_at DESC LIMIT 1`. If found, auto-confirm that report (create a `ReportReaction(confirm)` with the description as detail) and return the existing report
  4. If no dedup match, create new `Report` with all fields populated including `expires_at` from `compute_expires_at`
- Update `ReportCreatedOut` schema to include new fields: `direction`, `confirmCount`, `denyCount`, `expiresAt`
- Update router: keep `get_current_user_optional` dependency

**Test requirements:**
- Submit with valid active trip → report created with correct route+direction+expires_at
- Submit without active trip → 404
- Submit 6th report in an hour → 429
- Submit duplicate (same type+route+dir within 10 min) → existing report confirm_count incremented, no new report created
- Anonymous submit → report created with user_id=null

**Integrates with:** Steps 1-3

**Demo:** Start a trip, submit a DELAY report, verify response has auto-populated route/direction/expiresAt. Submit same type again within 10 min, verify dedup (confirm_count goes to 1, no new report ID).

---

## Step 5: GET /reports endpoint — list active reports by route+direction

**Objective:** Allow the frontend to query active (non-expired, non-resolved) reports for a specific route, optionally filtered by direction.

**Implementation guidance:**
- Add `GET /api/v1/reports` to `reports/router.py`
- Query params: `routeId` (required), `direction` (optional)
- Add `ReportsService.list_active(route_id, direction=None)`:
  1. Query reports where `route_id = :rid AND expires_at > now() AND status NOT IN ('resolved', 'dismissed')`
  2. If direction provided, add `AND direction = :dir`
  3. Order by `confirm_count DESC, created_at DESC`
  4. Return list of report dicts
- Add `ReportOut` schema for list response (same fields as `ReportCreatedOut` plus `latestDetail`)
- `latestDetail`: query the most recent confirm reaction with a non-null detail for each report

**Test requirements:**
- Returns only active, non-expired reports for the given route
- Direction filter works
- Expired reports excluded
- Resolved/dismissed reports excluded
- `latestDetail` populated from most recent confirm detail

**Integrates with:** Steps 1, 4

**Demo:** Submit a report, confirm it with detail text, call `GET /reports?routeId=400p&direction=sj_to_heredia`, verify the report appears with `latestDetail`.

---

## Step 6: POST /reports/{id}/confirm — confirmation with detail + expiry extension

**Objective:** Let users confirm a report, optionally adding context, extending its expiry and incrementing confirm count.

**Implementation guidance:**
- Add `POST /api/v1/reports/{id}/confirm` to `reports/router.py`
- Add `ReportConfirmIn` schema: `detail` (optional str, max 500 chars)
- Add `ReportsService.confirm(report_id, user, source_ip, detail)`:
  1. Fetch report by ID; 404 if not found
  2. If `expires_at < now()`, return 410 `ReportExpired`
  3. Check for existing reaction by this user (or IP if anonymous): if exists, update it; if not, create new `ReportReaction(reaction="confirm", detail=detail)`
  4. Increment `report.confirm_count` (recount from reactions to stay accurate)
  5. Extend `report.expires_at` by `REPORT_CONFIRM_EXTENSION_MINUTES[report.type]`
  6. If `confirm_count >= CONFIRM_THRESHOLD` and status is `new`, set status to `confirmed`
  7. Commit and return updated report

**Test requirements:**
- Confirm increments count and extends expiry
- Confirm with detail saves the detail text
- Double-confirm by same user updates existing reaction (no duplicate)
- Confirm on expired report → 410
- Confirm crossing threshold → status transitions to `confirmed`

**Integrates with:** Steps 1, 2, 5

**Demo:** Submit report, confirm it twice (from two users or one user + one anonymous), verify status transitions to `confirmed` and `expiresAt` extended.

---

## Step 7: POST /reports/{id}/deny — denial + auto-dismiss logic

**Objective:** Let users deny a report, dismissing it if denials outweigh confirmations.

**Implementation guidance:**
- Add `POST /api/v1/reports/{id}/deny` to `reports/router.py`
- Add `ReportsService.deny(report_id, user, source_ip)`:
  1. Fetch report by ID; 404 if not found
  2. If `expires_at < now()`, return 410
  3. Upsert `ReportReaction(reaction="deny")` for this user/IP
  4. Recount `deny_count` from reactions
  5. If `deny_count > confirm_count + DISMISS_MARGIN`, set status to `dismissed`
  6. Commit and return updated report

**Test requirements:**
- Deny increments deny_count
- Deny past threshold → status = dismissed
- Denied report no longer appears in `list_active`
- User who confirmed can switch to deny (reaction updated)

**Integrates with:** Steps 1, 5, 6

**Demo:** Submit report, deny it 3 times with no confirmations, verify status becomes `dismissed` and it disappears from `GET /reports`.

---

## Step 8: Arrivals integration — crowdReports field on ArrivalOut

**Objective:** Surface active crowd reports as a summary field on arrival cards so the frontend can show badges.

**Implementation guidance:**
- Add `CrowdReportSummary` schema in `arrivals/schemas.py`: `type` (str), `confirmCount` (int), `latestDetail` (str | None)
- Add `crowdReports: list[CrowdReportSummary] | None = None` field to `ArrivalOut`
- In `ArrivalsService._compute_arrivals()`:
  1. After building results, collect all distinct `route_id` values from results
  2. Query active reports: `SELECT route_id, direction, type, confirm_count FROM reports WHERE route_id IN (:route_ids) AND expires_at > now() AND status NOT IN ('resolved', 'dismissed')`
  3. For each report, fetch latest confirm detail (single query with window function or subquery)
  4. Build a map: `(route_id, direction) → list[CrowdReportSummary]`
  5. Attach to each result based on matching route (direction matching requires knowing the arrival's direction — use the route_stops direction lookup from the stop+route context)
- Keep the query batched (one query for all routes in the response, not N+1)

**Test requirements:**
- Arrival for a route with active confirmed report includes `crowdReports` in response
- Arrival for a route with no reports has `crowdReports: null`
- Expired reports don't appear in `crowdReports`
- Multiple report types on same route all surface

**Integrates with:** Steps 1, 4-7

**Demo:** Submit and confirm a DELAY report on 400p, call `GET /arrivals/stops/her_hospital`, verify the 400p arrival card includes `crowdReports: [{ type: "DELAY", confirmCount: 2, latestDetail: "..." }]`.

---

## Step 9: Backend deploy — migrate Neon + deploy to Fly + smoke test

**Objective:** Apply the database migration to production (Neon), deploy the updated backend to Fly, and run smoke tests against the live API to verify everything works before starting frontend work.

**Implementation guidance:**

**9a. Migrate Neon database:**
- Use the Neon MCP tools to inspect the current schema: `mcp__Neon__describe_table_schema` on `reports` table to confirm pre-migration state
- Create a Neon branch for safe migration testing: `mcp__Neon__create_branch` from main
- Run the Alembic migration against the branch first: `mcp__Neon__run_sql` to verify the migration SQL (new columns on `reports`, new `report_reactions` table, indexes)
- Verify with `mcp__Neon__describe_table_schema` on the branch
- If clean, run migration against the main branch (production)
- Verify production schema with `mcp__Neon__describe_table_schema`
- Clean up the test branch: `mcp__Neon__delete_branch`

**9b. Deploy to Fly:**
- Commit all backend changes (Steps 1-8)
- `git push origin main`
- `fly deploy`
- Monitor deployment logs for startup errors

**9c. Smoke test against live API:**
- `GET /api/v1/health` — verify app is up
- `POST /api/v1/auth/login` — get a valid JWT token
- `POST /api/v1/planner/trips/{id}/start` — start an active trip
- `POST /api/v1/reports` — submit a test DELAY report with the active trip
- `GET /api/v1/reports?routeId=400p` — verify the report appears
- `POST /api/v1/reports/{id}/confirm` — confirm the report
- `GET /api/v1/arrivals/stops/{stop_id}` — verify `crowdReports` field appears on the arrival card
- Clean up: resolve the test report or let it expire

**Test requirements:**
- Migration applies without data loss on existing reports
- All new endpoints respond with correct status codes on production
- `crowdReports` field appears in arrivals response
- No 500 errors in Fly logs

**Integrates with:** Steps 1-8

**Demo:** Hit the live API at `https://transitpulse-backend.fly.dev/api/v1/reports?routeId=400p` and see an empty list (or the test report). Verify the arrivals endpoint returns the new `crowdReports` field.

---

## Step 10: Frontend — report submission from active trip view

**Objective:** Add a "Report" button on the active trip view (bus steps) that opens a form to submit a report.

**Implementation guidance:**
- Re-run OpenAPI codegen (`gen:api`) to pick up new schema types and endpoints
- Add a "Report" button/icon on bus step cards in the active trip view (only visible when trip is in_progress)
- On tap, show a bottom sheet or modal with:
  - Report type selector (icons + labels for each type)
  - Optional description text input (max 500 chars)
  - Submit button
- On submit, call `POST /api/v1/reports` with `{ activeTripId, type, description }`
- Show success toast on creation; show error toast on 429 (rate limit) or 404
- Handle dedup response gracefully (report was auto-confirmed, show "Report added to existing")

**Test requirements:**
- Report button only visible during active trip on bus steps
- Submitting a report shows success feedback
- Rate limit error shows appropriate message
- Dedup case shows "added to existing" message

**Integrates with:** Step 4, frontend codebase

**Demo:** Start a trip in the browser, tap Report on a bus step, select DELAY, submit. Verify toast appears and report is created in the DB.

---

## Step 11: Frontend — crowd report badges on arrival/trip cards

**Objective:** Display badge icons on arrival cards when active crowd reports exist for that route+direction.

**Implementation guidance:**
- Re-run OpenAPI codegen if not done in Step 10
- In the arrival card component, check `crowdReports` field
- If non-null and non-empty, render a small badge icon corresponding to the report type (warning triangle for DELAY, people icon for OVERCROWDING, etc.)
- Badge shows the confirm count as a small number overlay (e.g., "3" next to the icon)
- Tapping the badge navigates to the report detail view (Step 12)

**Test requirements:**
- Badge appears when `crowdReports` is populated
- Badge does not appear when `crowdReports` is null
- Correct icon per report type
- Multiple report types show multiple badges

**Integrates with:** Steps 8, 9

**Demo:** With an active confirmed report on 400p, open the arrivals view for a Heredia stop. Verify the 400p card shows a delay badge with the confirm count.

---

## Step 12: Frontend — confirm/deny UI on report detail

**Objective:** When a user taps a crowd report badge, show report details with confirm/deny buttons.

**Implementation guidance:**
- Create a report detail bottom sheet or expandable section showing:
  - Report type + icon
  - Description text
  - Time since report ("reported 5 min ago")
  - Confirm count and deny count
  - Latest detail text from confirmations
  - "I see this too" (confirm) button with optional detail input
  - "Not anymore" (deny) button
- On confirm: call `POST /api/v1/reports/{id}/confirm` with optional detail
- On deny: call `POST /api/v1/reports/{id}/deny`
- After reacting, refresh the arrival data (React Query invalidation)
- Disable buttons if user already reacted (show their current reaction)

**Test requirements:**
- Report detail shows all fields correctly
- Confirm button calls correct endpoint and refreshes data
- Deny button calls correct endpoint and refreshes data
- Already-reacted state shown correctly

**Integrates with:** Steps 6, 7, 11

**Demo:** Tap a report badge on an arrival card, see report detail, confirm with detail text "about 10 min delay". Verify the confirm count increments and detail appears. Deny from another session, verify deny count updates.

---

## Step 13: Frontend deploy — deploy to Vercel + end-to-end smoke test

**Objective:** Deploy the frontend changes to Vercel and run an end-to-end smoke test across the full stack (Vercel frontend + Fly backend + Neon DB).

**Implementation guidance:**

**13a. Deploy to Vercel:**
- Commit all frontend changes (Steps 10-12)
- Push to the frontend repo
- Use `mcp__plugin_vercel_vercel__deploy_to_vercel` for a preview deployment first
- Verify preview deployment via `mcp__plugin_vercel_vercel__get_deployment` — check build logs for errors
- If clean, promote to production

**13b. End-to-end smoke test on production:**
- Open the live app in a browser
- **Report submission flow:**
  1. Search for a Heredia to San Jose trip
  2. Start the trip
  3. Tap Report on a bus step
  4. Submit a DELAY report with description
  5. Verify success toast
- **Badge display flow:**
  1. Navigate to arrivals for a Heredia stop
  2. Verify the 400p card shows a delay badge with confirm count
  3. Tap the badge to open report detail
- **Confirm/deny flow:**
  1. Tap "I see this too" on the report detail
  2. Add detail text
  3. Verify confirm count increments
  4. Verify badge updates
- **Expiry flow:**
  1. Wait for the test report to expire (or manually resolve it)
  2. Verify badge disappears from arrival card

**13c. Verify no regressions:**
- Check existing features still work: trip search, arrivals, active trip progression
- Monitor Sentry for new errors
- Check Fly logs for 500s via `fly logs`

**Test requirements:**
- Preview deployment builds without errors
- All smoke test flows pass on production
- No regressions in existing features
- No new Sentry errors

**Integrates with:** Steps 9-12

**Demo:** Full end-to-end: open the live app, start a trip, submit a report, see the badge on arrivals, confirm it, watch it expire. The crowdsourcing feature is live.

---

## Phase 2: Crowd-Adjusted Predictions

---

## Step 14: Backend — crowd delay adjustment config + logic in arrivals service

**Objective:** When active DELAY, BREAKDOWN, or ACCIDENT reports exist for a route, shift the predicted departure times forward (adding delay) proportional to report type and confirmation count.

**Implementation guidance:**
- Add delay adjustment constants to `app/modules/reports/config.py`:
  - `CROWD_DELAY_BASE_MINUTES`: base delay per report type (e.g. DELAY=3, BREAKDOWN=8, ACCIDENT=10)
  - `CROWD_DELAY_PER_CONFIRM_MINUTES`: extra delay per confirmation (e.g. DELAY=1, BREAKDOWN=2, ACCIDENT=2)
  - `CROWD_DELAY_MAX_MINUTES`: cap per report type (e.g. DELAY=15, BREAKDOWN=30, ACCIDENT=30)
  - Only reports with `confirm_count >= CONFIRM_THRESHOLD` (2) trigger adjustments — unconfirmed reports are signals, not adjustments
- In `ArrivalsService._compute_arrivals()`, after attaching `crowdReports`:
  1. Build a delay map: `route_id → total_delay_minutes` from active delay-type reports
  2. For each result with a prediction, if its route has a crowd delay:
     - Shift `predictedDeparture` by `+delay_minutes`
     - Shift `windowLow` and `windowHigh` by `+delay_minutes`
     - Recalculate `etaSec` from shifted `predictedDeparture`
     - Widen confidence window slightly (add 1 min to std) to reflect crowd uncertainty
     - Set `crowdAdjusted = True` on the prediction
  3. For fallback (schedule-based) arrivals with no prediction object, apply the delay directly to `etaSec`
- Multiple delay-type reports on the same route stack (DELAY + ACCIDENT), but cap total at `max(CROWD_DELAY_MAX_MINUTES)` = 30 min

**Test requirements:**
- Arrival with confirmed DELAY report → etaSec increased, prediction shifted
- Unconfirmed report (0-1 confirms) → no adjustment
- Multiple report types stack correctly
- Total delay capped at max
- Expired/dismissed reports don't affect predictions

**Integrates with:** Steps 2, 8 (crowd_map already computed)

**Demo:** Submit and confirm a DELAY report on 400p. Call `GET /stops/s1` and verify the 400p arrival's `etaSec` is higher than the scheduled time, and `prediction.crowdAdjusted` is `true`.

---

## Step 15: Backend — occupancy boost from OVERCROWDING reports

**Objective:** When active OVERCROWDING reports exist for a route, bump the occupancy value on arrival cards.

**Implementation guidance:**
- In `ArrivalsService._compute_arrivals()`, after the delay adjustment pass:
  1. Check `crowd_map` for OVERCROWDING reports with `confirm_count >= CONFIRM_THRESHOLD`
  2. For matching routes, increase `occupancy` by 1 per confirmed OVERCROWDING report (cap at 4)
- This is simpler than delay — no prediction shifting, just the occupancy integer

**Test requirements:**
- Confirmed OVERCROWDING → occupancy bumped
- Unconfirmed OVERCROWDING → no change
- Occupancy caps at 4

**Integrates with:** Step 14

**Demo:** Submit and confirm an OVERCROWDING report on 400p. Verify the arrival card shows higher occupancy.

---

## Step 16: Schema — add `crowdAdjusted` flag to ArrivalPrediction

**Objective:** Add a boolean field to the prediction schema so the frontend knows when an ETA was crowd-adjusted.

**Implementation guidance:**
- Add `crowdAdjusted: bool = False` to `ArrivalPrediction` in `app/modules/arrivals/schemas.py`
- Add `crowdAdjusted?: boolean` to the frontend `ArrivalPrediction` type in `src/types/transit.ts`
- Set to `True` in the arrivals service when crowd delay is applied (Step 14)

**Test requirements:**
- Field defaults to `false` when no crowd adjustment
- Field is `true` when delay was applied

**Integrates with:** Step 14

**Demo:** Compare two arrivals — one with crowd delay, one without. Verify the flag differs.

---

## Step 17: Backend deploy — deploy to Fly + smoke test

**Objective:** Deploy the prediction adjustment logic to production.

**Implementation guidance:**
- Deploy to Fly: `fly deploy`
- Smoke test:
  - `GET /stops/{stop}` — verify predictions still return correctly with no active reports
  - Submit + confirm a DELAY report → verify shifted ETA in arrivals
  - Verify `crowdAdjusted` flag in response

**Test requirements:**
- No regression in normal predictions
- Crowd-adjusted predictions visible in production

**Integrates with:** Steps 14-16

**Demo:** Hit live API, verify predictions are crowd-adjusted when reports are active.

---

## Step 18: Frontend — crowd-adjusted ETA indicator on arrival badges

**Objective:** Show a visual indicator on the ETA badge when the prediction was crowd-adjusted.

**Implementation guidance:**
- In the `EtaBadge` component, check `prediction.crowdAdjusted`
- When true, add a small crowd icon or tint the badge differently (e.g. warning-colored border, "~" prefix on the time, or a small people icon)
- Tooltip or tap detail: "ETA adjusted based on X crowd reports"

**Test requirements:**
- Indicator visible when `crowdAdjusted` is true
- No indicator when false or prediction is null

**Integrates with:** Steps 11, 16

**Demo:** With an active confirmed delay report, view arrivals and see the crowd-adjusted indicator on the affected route's ETA badge.

---

## Step 19: Frontend deploy — deploy to Vercel + e2e verify

**Objective:** Deploy frontend changes and verify the full crowd-adjusted predictions flow end-to-end.

**Implementation guidance:**
- `vercel deploy --prod`
- Verify: arrival cards show crowd-adjusted indicators when delay reports are active
- Verify: indicators disappear when reports expire or are dismissed

**Test requirements:**
- Build succeeds, tests pass
- E2e flow works on production

**Demo:** Full flow on the live app — submit delay report, confirm it, see ETA shift and crowd indicator on arrival card.
