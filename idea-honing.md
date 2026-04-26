# Idea Honing — TransitPulse Backend v1

This document captures the iterative requirements clarification for the TransitPulse backend v1, building on top of `rough-idea.md` (the canonical backend spec).

Format: each entry is a **Question** followed by the **Answer** (final decision), with optional **Options considered**.

---

## Q1 — Planner search input semantics

**Question:** `GET /api/planner/search` takes `from` and `to` as strings. The spec says the v1 implementation is "rule-based search over seeded route/stop data" — but it does not say *how* the strings are interpreted. How should the backend resolve `from` and `to` in v1?

**Options considered:**

- **A. Stop-ID / stop-name match only** — strings must be either a known `stopId` or a case-insensitive exact stop name. Any other input → `404` (or empty result).
- **B. Fuzzy stop / neighborhood match** — strings are matched against stop names, route long-names, and a small seeded "places/neighborhoods" table using ILIKE / trigram similarity. Best matches resolve to candidate origin/destination stops.
- **C. Lat,lng coordinates** — strings are parsed as `"lat,lng"` and the nearest seeded stop within some radius is chosen. Free-text not supported in v1.
- **D. Hybrid** — accept either coordinates OR free-text, and fall back to fuzzy matching for free-text.
- **E. Other** — describe.

**Sub-question:** When the input cannot be resolved to any known origin/destination, what should the response be — empty `TripOption[]` (`200`), an error (`400` / `404`), or a structured "ambiguous" response with suggestions?

**Answer:**

- **Input model: D — Hybrid.** Accept either `"lat,lng"` coordinates or free text. Free text falls back to fuzzy matching against seeded stop names, route long-names, and a small "neighborhoods/places" table.
- **Unresolved input:** `200 OK` with an empty `TripOption[]`. No `404`, no "did you mean?" suggestions in v1.

**Implications to carry into design:**

- Need a tiny `places` (or equivalent) seed source so neighborhoods/landmarks resolve, in addition to stop names and route names.
- Free-text matching uses Postgres-native tooling (`ILIKE`, `pg_trgm`) — no external geocoder in v1.
- A `lat,lng` parser at the API boundary distinguishes coordinate inputs from free text before fuzzy matching.
- Empty results are a normal (non-error) outcome; the frontend must already handle the "no trips found" UI state.

---

## Q2 — How are `TripOption`s produced?

**Question:** The spec says the planner is "rule-based search over seeded route/stop data" and lists `trip_templates` as a required table — but it does not pin down whether trip options are computed live or pre-baked. How should v1 produce `TripOption[]`?

**Options considered:**

- **A. Live computation.** Walk the `route_stops` graph at search time. `trip_templates` is a persistence shim that stores each returned option so `tripId`s are stable for follow-up calls (`/trips/{tripId}`, `/start`, `/advance`).
- **B. Pre-baked templates.** Seed every viable (origin, destination, route) row in `trip_templates`. Search is a `SELECT`. Limited to seeded combinations.
- **C. Hybrid.** Pre-baked for common cases, live fallback otherwise.
- **D. Other.**

**Answer: A — Live computation.**

**Implications to carry into design:**

- Planner walks `route_stops` to assemble itineraries; for v1, the seeded graph is small enough that brute-force (single-route direct + simple one-transfer) is sufficient.
- After computation, each candidate option is persisted as a `trip_templates` row so its `tripId` survives across requests.
- Need a dedup / hash strategy on `trip_templates` so repeated searches do not balloon the table — likely a content hash of (origin_stop_id, destination_stop_id, ordered_route_ids).
- Sort modes (`fastest | cheapest | fewest`) operate on the live-computed candidate set before persistence.

---

## Q3 — Active trip lifecycle

**Question:** The spec defines `start` and `advance` endpoints, says active trip state is backend-owned, and lists a `status` column — but does not pin down concurrency, anonymous addressing, the state machine, completion triggers, or re-start semantics.

**Answer:**

- **Concurrency:** one in-progress active trip per user (or per anonymous client) at any time.
- **Anonymous active trips:** allowed. `/start` returns an opaque `activeTripId`; the client must echo it back on subsequent `/advance` calls.
- **State machine:** `in_progress | completed | cancelled | abandoned`. (`abandoned` is reserved for a future auto-timeout sweep; v1 may not implement the sweep itself but the state value is part of the enum from day one.)
- **Completion trigger:** when `/advance` is called with `currentStepIndex` equal to the final step, the backend auto-transitions the trip to `completed`. No separate `/complete` endpoint in v1.
- **Re-start semantics:** if `/start` is called for the same `tripId` while the same user/client already has an `in_progress` trip for that template, return the existing active trip instead of creating a new one.

**Implications to carry into design:**

- `active_trips.status` is an enum with four values from day one.
- Need an addressing strategy for anonymous active trips on `/advance` — followed up in Q4.
- Re-start is idempotent for the same (user, tripId) pair.
- Cancellation needs an endpoint surface or a request shape — not in the canonical spec; flag for a later question if it becomes load-bearing.

---

## Q4 — Anonymous addressing for `/advance` (and `/start` re-entry)

**Question:** The canonical spec body for `/advance` is `{ "currentStepIndex": 1 }` and the URL path key is `tripId` (the trip-template), not `activeTripId`. For authenticated users that resolves cleanly; for anonymous clients there is no session, so the backend cannot identify which active trip is being advanced.

**Options considered:**

- **A. Extend the body** with an optional `activeTripId`. Smallest deviation from the spec; no new URLs.
- **B. Add a parallel URL** (`/api/planner/active-trips/{activeTripId}/advance`).
- **C. Header-based** addressing (`X-Active-Trip-Id`).
- **D. Disallow anonymous active trips.**

**Answer: A — Extend the body with an optional `activeTripId`.**

**Implications to carry into design:**

- `POST /api/planner/trips/{tripId}/start` response — `ActiveTripDto` — must include `activeTripId` so clients can echo it back.
- `POST /api/planner/trips/{tripId}/advance` body becomes `{ currentStepIndex, activeTripId? }`.
  - Authenticated callers: `activeTripId` optional; backend resolves from `user_id + tripId`.
  - Anonymous callers: `activeTripId` required; missing it → `400 Bad Request`.
- If `activeTripId` is supplied but does not belong to the `tripId` in the URL, return `404`.
- Re-start (`/start`) for an authenticated user with an existing in-progress trip on the same template returns the existing `ActiveTripDto` (per Q3); for anonymous re-start there is no way to look up "the existing trip" without an `activeTripId` in the request, so anonymous `/start` always creates a new active trip.

---

## Q5 — i18n strategy

**Question:** The spec stores alerts bilingually (`title_es/title_en`, `body_es/body_en`) but leaves other entities and the API response shape unspecified. Pin down which entities are bilingual, what the canonical column language is for non-bilingual data, the alerts API response shape, and the language of error messages.

**Answer:**

- **Bilingual entities (v1):** alerts only. All other entities (routes, stops, reports, etc.) are single-language at the data layer.
- **Canonical column language for non-bilingual data:** Spanish.
- **Alerts API response shape:** Option A — return both fields side-by-side (`titleEs`, `titleEn`, `bodyEs`, `bodyEn`). Language selection is pushed to the frontend.
- **API error messages:** English-only (diagnostic, not user-facing copy).

**Implications to carry into design:**

- Pydantic schemas for alerts surface both languages; no `Accept-Language` handling in v1.
- Schemas for routes, stops, reports use a single name/description field, populated in Spanish.
- Error envelopes use English `detail`/`code` strings consistently across all modules.
- Frontend remains the language-selection authority; backend never picks a language for the user.

---

## Q6 — Auth UX and JWT details

**Question:** The spec leaves auth UX open and the data model already has `password_hash`. Pin down which auth flow ships in v1, JWT lifetime, signing algorithm, and claim set.

**Answer:**

- **Auth UX:** Email + password.
  - `POST /api/auth/register` body: `{ email, password, displayName }` → `201 Created`.
  - `POST /api/auth/login` body: `{ email, password }` → `200 OK` with `{ accessToken, expiresAt }`.
- **Token lifetime:** single access token, 24h. No refresh token in v1.
- **Signing:** symmetric HS256 with a single env-managed secret.
- **Claims:** `sub` (user id), `iat`, `exp`, `email`.

**Implications to carry into design:**

- `users.password_hash` is populated via a strong KDF (bcrypt or argon2) — pinned in the design doc.
- `GET /api/users/me` requires a `Authorization: Bearer <jwt>` header; missing/invalid → `401`.
- No refresh endpoint, no token revocation list, no rotation in v1 — accept the trade-off that a leaked token is valid until `exp`.
- JWT secret is a single env var (`JWT_SECRET`), 32+ bytes, loaded via the config module.
- A small password policy lives in the auth module (e.g., min 8 chars) — not a deal-breaker if relaxed; it is a v1 default, not a contract.

---

## Q7 — Lambda packaging strategy

**Question:** The spec says "FastAPI application packaged for Lambda" without choosing an adapter, an artifact format, or an API Gateway flavor.

**Options considered:**

- **A.** Mangum + zip-or-container + HTTP API.
- **B.** AWS Lambda Web Adapter + container image + HTTP API.
- **C.** Custom Lambda runtime / hand-rolled handler.

**Answer: B — AWS Lambda Web Adapter + container image + API Gateway HTTP API.**

**Implications to carry into design:**

- The same container image is the deploy artifact in production and the runtime artifact in `docker compose` locally.
- Dockerfile pulls the AWS Lambda Web Adapter binary (`COPY --from=public.ecr.aws/awsguru/aws-lambda-adapter:<version> /lambda-adapter /opt/extensions/lambda-adapter`).
- Backend process is `uvicorn app.main:app --host 0.0.0.0 --port 8080` — identical locally and in Lambda. The adapter forwards API Gateway HTTP API events to that port.
- API Gateway flavor is HTTP API (v2). Routes proxy `/{proxy+}` to the Lambda function URL/integration.
- CI builds and pushes the image to ECR; Lambda function references it by digest.
- Local `docker-compose.yml` exposes the same container on port 8080 (or similar) without the adapter taking effect — adapter activates only when `AWS_LAMBDA_RUNTIME_API` is present.
- Cold-start cost is acceptable trade-off for stronger local/prod parity.

---

## Q8 — Seed data scope

**Question:** The spec lists seed files but does not pin down the city, the scale, or how arrivals are generated.

**Answer:**

- **City / region:** Costa Rican Gran Área Metropolitana (GAM), centered on Heredia and San José routes.
- **Scale:** Tiny demo set (~5 routes, ~30 stops, ~3 trip-template patterns). Fabricated but plausible.
- **Arrivals strategy:** Seed an `arrival_schedules` table with `(route_id, stop_id, weekday, first_service, last_service, headway_minutes)`. ETAs are computed at request time as `next_departure - now()`.

**Implications to carry into design:**

- Seed files: `routes.json`, `stops.json`, `alerts.json`, `trips.json`, plus `arrival_schedules.json` (a new seed surface flowing from this decision).
- Stop names, route `long_name`s, alert `_es` fields, and place names use Costa Rican Spanish — neighborhoods like Heredia centro, San Pedro, Sabana, Pavas, Curridabat, Mercedes Norte, etc.
- A small `places` (or equivalent) seed table is added to support free-text fuzzy matching from Q1 — landmarks like UCR, UNA, Mall San Pedro, Aeropuerto Tobías Bolaños.
- A new `arrival_schedules` table joins the data model — not in the original spec table list, but flows directly from this decision and §8.3's "arrivals may be generated from seeded schedules plus simple heuristics."
- At ~5 routes / ~30 stops the planner graph walk is trivially fast — direct + one-transfer brute force is more than sufficient.
- Trip templates are pre-seeded only in the sense that common patterns exist; computation is still live (Q2).

---

## Q9 — Test database strategy

**Question:** The spec mandates tests but does not pin down how tests get a Postgres to run against — a real concern given Postgres-specific features (e.g., `pg_trgm` from Q1) and the no-SQLite-fallback stance.

**Answer:**

- **Strategy: A — Docker Compose Postgres + transactional rollback per test.**
- **Container layout: A1 — same Postgres container as dev, separate logical database (`transitpulse_test`).** No second compose service.

**Implications to carry into design:**

- Test fixture (`pytest` `conftest.py`) opens a SQLAlchemy session inside a transaction at test start and rolls back at teardown — schema persists across runs, data does not.
- A one-time migration step (Alembic) sets up the `transitpulse_test` database before the first test run; CI script idempotently re-applies migrations.
- Tests assume Postgres is reachable on the same host/port as dev, just with a different database name; `DATABASE_URL` is environment-driven so tests pass `transitpulse_test` while local dev passes `transitpulse`.
- API tests use FastAPI's `TestClient` against the same app instance; the dependency-injection layer overrides the DB session to use the test transaction.
- `pg_trgm` and any other extensions must be installed in both `transitpulse` and `transitpulse_test` databases — handled by an Alembic migration that runs `CREATE EXTENSION IF NOT EXISTS pg_trgm`.

---

## Q10 — API standing decisions

**Question:** Five small but blocking conventions (versioning, CORS, pagination, rate limiting, error envelope) needed defaults before routers get written.

**Answer:** All five defaults accepted.

1. **API versioning:** `/api/v1/...` prefix on every route. `/api/...` from the spec is read as shorthand for "the API namespace." Adding a version now is cheap insurance.
2. **CORS:** explicit allow-list driven by env var `CORS_ORIGINS`, defaulting to `http://localhost:3000` locally. No wildcard.
3. **Pagination:** none in v1. `shared/pagination.py` exists as a `Page[T]` scaffold but no endpoint uses it. Documented limitation.
4. **Rate limiting:** documented v1 gap — no enforcement. Real rate limiting is deferred to API Gateway throttling once traffic exists.
5. **Error envelope:** custom shape — `{ "error": { "code": "string_enum", "message": "english string", "details": {} } }`. Codes are short identifiers (`not_found`, `validation_error`, `auth_required`, `forbidden`, `conflict`).

**Implications to carry into design:**

- Spec §9 endpoint paths in `rough-idea.md` are read with an implicit `/v1` insertion (e.g., `/api/v1/planner/search`).
- A FastAPI exception handler converts `HTTPException` and Pydantic `ValidationError` into the custom envelope; never leak default FastAPI error shapes.
- Auth failures use `auth_required` (401) and `forbidden` (403); 404s use `not_found`; 4xx body validation uses `validation_error`.
- `shared/exceptions.py` defines a small `AppError` base with a `code` attribute that the handler reads.
- CORS middleware is wired in `app.main` from `settings.cors_origins`.

---

## Q11 — Lambda + Postgres connection management

**Question:** Lambda's container model can exhaust Postgres `max_connections` under concurrency. Pin down the v1 connection strategy and the credential source.

**Options considered:**

- **A.** Plain SQLAlchemy pool per container (`pool_size=1, max_overflow=1`).
- **B.** RDS Proxy as a managed pooler.
- **C.** `NullPool` — open a fresh connection per request.

**Answer: A — plain SQLAlchemy pool, `pool_size=1, max_overflow=1`, plus plain env-var `DATABASE_URL` for credentials.**

**Implications to carry into design:**

- SQLAlchemy engine is built with `pool_size=1, max_overflow=1, pool_pre_ping=True, pool_recycle=600`.
- Engine is created at module import time so warm Lambda invocations reuse the connection across calls; cold starts pay one connection setup.
- `DATABASE_URL` is read from env via Pydantic `BaseSettings`; no AWS Secrets Manager fetch in v1.
- Design doc explicitly notes RDS Proxy as the upgrade path once concurrent Lambda executions push toward `max_connections`. Documented v1 gap.
- Local dev container reads the same `DATABASE_URL` form, just pointing at the local Postgres host.

---

## Q12 — Operational standing decisions

**Question:** Pin down logging, health check, and migration bootstrap before the design doc.

**Answer:** All three defaults accepted.

1. **Logging:** structured JSON to `stdout`. Every request has a request ID (from `X-Request-Id` header if present, else generated). Log lines include `request_id`, `path`, `method`, `status`, `latency_ms`. CloudWatch ingests stdout natively. No external APM in v1.
2. **Health check:** `GET /api/v1/health` returns `{ "status": "ok" }` plus a shallow `SELECT 1` DB ping. Open (no auth). Used by API Gateway warm-up and local Docker compose `healthcheck:` directive.
3. **Migrations bootstrap:** single initial Alembic migration `0001_initial` creates every v1 table and `CREATE EXTENSION IF NOT EXISTS pg_trgm` in one shot. Subsequent changes get their own migrations.

**Implications to carry into design:**

- A FastAPI middleware sets `request_id` on `request.state` and emits the access log line at response time.
- `shared/logging.py` configures the JSON formatter and is imported once from `app.main`.
- Health check lives in its own tiny module (`app/modules/health/router.py`) to keep the dependency graph clean — does not depend on auth, does not depend on any business module.
- The single initial migration is generated after every v1 model is in place; we do not autogenerate migrations incrementally during v1 implementation. Greenfield — the migration is created at the end of the model-building step, not during.

---

## Q13 — Reports & reputation domain

**Question:** The spec lists `reports.type`, `reports.status`, and `users.reputation_score` without enumerations or behavior. Pin down enums, v1 reputation behavior, and anonymous-report abuse protection.

**Answer:** All four defaults accepted.

1. **`reports.type` enum:** `delay | breakdown | accident | overcrowding | route_change | safety | other`.
2. **`reports.status` enum and lifecycle:** `new | confirmed | dismissed | resolved`. Default on creation is `new`. v1 has no moderation UI; reports stay `new` indefinitely. The full enum is present from day one to support future moderation without migration churn.
3. **Reputation behavior in v1:**
   - `users.reputation_score` is **scaffolding only** — defaults to `0`, never mutated by v1 logic. The column exists for attribution and to keep the schema stable for v1.x moderation work.
   - `user_reputation_events` table is **deferred** — not created in v1.
4. **Anonymous-report abuse protection:** none in v1; documented gap. The backend captures the request IP opportunistically into `reports.source_ip` (nullable) so future moderation has data to work with.

**Implications to carry into design:**

- `reports` table gains a nullable `source_ip` column on top of the spec's listed fields.
- A Pydantic enum for `ReportType` and `ReportStatus` lives in `app/modules/reports/schemas.py`; the SQLAlchemy model uses `sa.Enum` mapped to these.
- The `users` model includes `reputation_score INTEGER NOT NULL DEFAULT 0` but no service writes to it in v1.
- Future moderation work has a clear surface: introduce `user_reputation_events`, wire status transitions, add a moderator role — none of which requires breaking v1 schemas.

---

## Q14 — Contract reconciliation (post-research)

**Question:** Reading `TransitPulseWebsite/src/data/contracts/*.ts`, `src/types/transit.ts`, `src/data/transit.ts`, and the mock providers surfaced five places where the canonical contracts deviate from the backend spec or from prior Q&A answers. (Detailed in `research/frontend-contracts.md`.)

**Answer:** All five resolutions accepted as recommended.

- **C1 (i18n strategy) → R1 — honor the contract literally.** Stops and alerts ship i18n lookup keys (`nameKey`, `addrKey`, `titleKey`, `bodyKey`); arrivals and every trip-step variant ship inline bilingual text (`_es`/`_en` pairs). **This supersedes Q5.** Seed data uses the exact keys already present in the frontend `I18N` table (`stop_1`, `stop_1_addr`, `alert_1_title`, etc.). Adding a new stop or alert requires both a backend seed entry and a matching `I18N` table entry — coupling is documented as a v1 trade-off.
- **C2 (`ActiveTripDto` addressing) → R1 — extend the DTO** with an optional `activeTripId` field. Authenticated callers may ignore it; anonymous callers echo it back on `/advance`. **This supersedes Q4** in the sense that the DTO gains the field; the body-extension decision from Q4 is unchanged.
- **C3 (`Alert.time` shape) → R1 — backend ships ISO `emittedAt`** as a string; frontend formats. The spec's `alerts.emitted_at` column maps directly to the wire field. The `time: string` field name in the contract is treated as the relative-formatted string the frontend computes.
- **C4 (`Stop.dist`) → R2 — distance computed from optional `?lat=&lng=` query params** via Haversine on `stops.lat/lng`. When the query params are absent, `dist` returns `0`. This unlocks the future "near me" UX without extra schema work.
- **C5 (`confidence`/`occupancy` on `TripOption`) → ratified heuristics.**
  - `confidence = clamp(1.0 - 0.05 * transfers - walkMin / 60.0, 0, 1)`
  - `occupancy = max(step.occ for step in steps if step.kind == "bus")`, else `0`

**Implications to carry into design (in addition to those captured in `research/frontend-contracts.md`):**

- Backend `stops` table keeps `name_key` and `addr_key` columns (text, not nullable) in place of the spec's `name`/`address`. Display text lives only in the frontend `I18N` table.
- Backend `alerts` table keeps `title_key` and `body_key` columns (text, not nullable) in place of the spec's `title_es/title_en/body_es/body_en`. Display text lives only in the frontend `I18N` table.
- Backend `arrivals` (computed at request time, not persisted directly) and `active_trip_steps.payload_json` carry inline `_es`/`_en` text fields for arrival destinations, walk targets, bus origins/destinations, and transfer targets.
- The `places`/`landmarks` seed table from Q1 stores its own keys/text — likely follows the inline `_es/_en` pattern since places are not in the `I18N` table.
- `active_trips` table gains an `activeTripId` (UUID surrogate) exposed in the wire DTO; the integer `id` PK can stay internal.
- A coordinated "seed key vs `I18N` key" check belongs in tests — a unit test that asserts every seeded `nameKey`/`addrKey`/`titleKey`/`bodyKey` exists in the frontend `I18N.es` table (loaded from a frozen snapshot in the test fixture).
