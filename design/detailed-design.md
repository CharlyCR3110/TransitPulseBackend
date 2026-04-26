# TransitPulse Backend v1 — Detailed Design

> Status: design (PDD step 6). Standalone — does not require reading `rough-idea.md`, `idea-honing.md`, or the `research/` files to follow.

---

## 1. Overview

TransitPulse v1 is a transit-information backend serving a Next.js frontend that already exists. It supports one end-to-end product slice for the Costa Rican Gran Área Metropolitana (GAM): trip search, trip detail, in-trip step advancement, stops, arrivals, alerts, user reports, and a lightweight account system that anchors crowdsourced reports.

The backend is a Python/FastAPI **modular monolith** packaged as a single container image. The same image runs locally under Docker Compose (with Postgres) and in production on **AWS Lambda + API Gateway HTTP API** via the **AWS Lambda Web Adapter**. The only required datastore is **PostgreSQL 16**. There is no Redis, no queue, no background worker, no WebSocket, and no caching layer in v1.

### 1.1 Locked decisions snapshot

| Area | v1 decision |
|---|---|
| Language / framework | Python 3.12, FastAPI, Pydantic v2 |
| Persistence | PostgreSQL 16, SQLAlchemy 2.x, Alembic migrations |
| Deployment | Container image → AWS Lambda + API Gateway HTTP API |
| Adapter | AWS Lambda Web Adapter (uvicorn on port 8080 inside the container) |
| Local stack | `docker compose up` → backend + postgres |
| API namespace | `/api/v1/...` |
| Auth | Email/password + JWT HS256, 24h access token, no refresh |
| i18n | Mixed: lookup keys for stops/alerts, inline `_es`/`_en` for arrivals & trip steps |
| Active trip | Backend-owned; one in-progress per user/client; anonymous OK with `activeTripId` |
| Cache / queue | None |
| Rate limiting | Documented gap (deferred to API Gateway throttling) |
| Pagination | None in v1 (`Page[T]` scaffold exists, unused) |
| Tests | Postgres + transactional rollback; same container, `transitpulse_test` DB |
| Logging | Structured JSON to stdout + per-request `request_id` |

### 1.2 Out of scope

Payments, subscriptions, favorites/personalization, ML pipelines, Redis, WebSockets, background workers, GTFS-grade routing, multi-region deployment, advanced moderation.

---

## 2. Detailed Requirements

Consolidated from the 14 honing decisions. Each numbered requirement is testable.

### 2.1 Functional requirements

**Planner (R-PL)**

- **R-PL-1.** `GET /api/v1/planner/search?from&to&sort` accepts `from` and `to` as either `"lat,lng"` coordinate strings or free-text strings (stop names, route long-names, neighborhood/landmark names). `sort ∈ {fastest, cheapest, fewest}`.
- **R-PL-2.** Free-text inputs are resolved by Postgres-native fuzzy match (`pg_trgm`) over stop names, route long-names, and a seeded `places` table. Coordinate inputs are resolved by nearest-stop Haversine within a configurable radius.
- **R-PL-3.** When either side is unresolved, the response is `200 OK` with an empty `TripOption[]`. No `404`, no "did you mean?" suggestions.
- **R-PL-4.** Trip options are computed live by walking the `route_stops` graph: direct routes plus single-transfer routes. The chosen sort is applied, then each returned option is persisted to `trip_templates` with a stable `tripId` so subsequent calls work.
- **R-PL-5.** `trip_templates` rows are deduplicated by a content hash of `(origin_stop_id, destination_stop_id, ordered_route_ids)` to prevent table bloat from repeated searches.
- **R-PL-6.** Each `TripOption` carries a `tag` ∈ `{fastest, cheapest, fewest}` derived from the requested sort.
- **R-PL-7.** `confidence` and `occupancy` on `TripOption`/`TripDetailDto` are computed deterministically:
  - `confidence = clamp(1.0 - 0.05 * transfers - walkMin / 60.0, 0, 1)`
  - `occupancy = max(step.occ for step in steps if step.kind == "bus")` else `0`
- **R-PL-8.** `GET /api/v1/planner/trips/{tripId}` returns `TripDetailDto` (`200`) or the standard `not_found` envelope (`404`).
- **R-PL-9.** `POST /api/v1/planner/trips/{tripId}/start` creates an active trip and returns `ActiveTripDto`. Behavior depends on auth + existing state:
  - **Authenticated + existing in-progress trip on the same `tripId`** → return the existing active trip (idempotent re-start).
  - **Authenticated + existing in-progress trip on a different `tripId`** → transition the previous trip to `cancelled`, then create a new `in_progress` trip. (Single-active-session model. Q3.1 says one in-progress per user, period.)
  - **Authenticated + no existing in-progress trip** → create.
  - **Anonymous** → always create. The previous anonymous trip (if any) is unreachable from the request anyway, so no implicit cancellation happens.
- **R-PL-10.** `POST /api/v1/planner/trips/{tripId}/advance` body: `{ currentStepIndex: number, activeTripId?: string }`. Authenticated callers may omit `activeTripId` (resolved from `(user_id, tripId)`). Anonymous callers must include it; missing → `422 validation_error`. If `activeTripId` does not match `tripId`, or no matching active trip exists, → `404 not_found`.
- **R-PL-11.** When `currentStepIndex` after increment equals the final step index, the active trip auto-transitions to `completed`.

**Stops (R-ST)**

- **R-ST-1.** `GET /api/v1/stops` returns `Stop[]` (no pagination in v1).
- **R-ST-2.** `GET /api/v1/stops?lat=&lng=` (both required if present) computes per-row `dist` (meters) via Haversine on `stops.lat/lng`. Without the params, `dist = 0`.
- **R-ST-3.** `GET /api/v1/stops/{stopId}` returns `StopDetailDto` (`200`) or `404`.
- **R-ST-4.** `Stop.nameKey` and `Stop.addrKey` are i18n lookup keys, not text. Translations live in the frontend `I18N` table.

**Arrivals (R-AR)**

- **R-AR-1.** `GET /api/v1/arrivals/home` returns the next `N` upcoming arrivals across all `stops.live=true`, sorted by ascending ETA seconds. `N` is `arrivals_home_limit` (default 6) — a v1 design call; not pinned by Q&A.
- **R-AR-2.** `GET /api/v1/arrivals/stops/{stopId}` returns upcoming arrivals for the given stop (`200`) or `404` if the stop is unknown.
- **R-AR-3.** Arrivals are computed at request time from `arrival_schedules` rows: for each `(route_id, stop_id)` matching the requested stop(s) and the current weekday, find the next departure inside `[first_service, last_service]` based on `headway_minutes`. ETA seconds = `next_departure_epoch - now()`.
- **R-AR-4.** Arrival `destEs` / `destEn` are read directly from the matching `arrival_schedules` row (`dest_es`, `dest_en` text columns — denormalized at seed time, no join required).
- **R-AR-5.** Arrival `status` is derived from active alerts:
  - If no active alert targets the arrival's route → `"ok"` (the contract permits both `"on-time"` and `"ok"`; v1 picks `"ok"` to match the mock data).
  - If at least one active alert targets the route, `status` = the worst alert severity for that route (`"bad"` overrides `"warn"` overrides `"ok"`). Severity strings map 1:1 — `bad`→`"bad"`, `warn`→`"warn"`, `ok`→`"ok"`.
- **R-AR-6.** Arrival `note_es` / `note_en` are always `null` in v1. (See G-11.) Users see disruption details by hitting `GET /api/v1/alerts`; inline notes on arrivals are deferred until the backend has a way to surface translated alert text without owning translations.

**Alerts (R-AL)**

- **R-AL-1.** `GET /api/v1/alerts` returns active alerts (`alerts.is_active = true`).
- **R-AL-2.** `GET /api/v1/alerts?routeIds=100,302,T1` filters by overlap with the alert's `routes` set.
- **R-AL-3.** `Alert.titleKey` and `Alert.bodyKey` are i18n lookup keys. The wire format also includes `emittedAt` (ISO 8601 string).

**Reports (R-RP)**

- **R-RP-1.** `POST /api/v1/reports` body: `{ type, routeId?, stopId?, description }`. Type ∈ `{delay, breakdown, accident, overcrowding, route_change, safety, other}`.
- **R-RP-2.** Both anonymous and authenticated submissions are accepted. Authenticated submissions associate `userId`. All submissions capture request IP into `reports.source_ip` (nullable) and a server-set `created_at` timestamp.
- **R-RP-3.** Initial `status` is `new`. v1 has no moderation surface; status remains `new`. The full enum (`new | confirmed | dismissed | resolved`) exists from day one.
- **R-RP-4.** Successful submission returns `201 Created` with the persisted report's ID and metadata.

**Users / Auth (R-AU)**

- **R-AU-1.** `POST /api/v1/auth/register` body: `{ email, password, displayName }` → `201 Created` with the created user (no token returned at this stage).
- **R-AU-2.** `POST /api/v1/auth/login` body: `{ email, password }` → `200 OK` with `{ accessToken, expiresAt }`.
- **R-AU-3.** `GET /api/v1/users/me` requires `Authorization: Bearer <jwt>`; returns the current user's profile (`200`) or `401 auth_required`.
- **R-AU-4.** Passwords stored with a strong KDF (argon2 preferred, bcrypt acceptable). JWT signed HS256 with `JWT_SECRET` env var (32+ bytes).
- **R-AU-5.** JWT claims: `sub` (user id), `iat`, `exp`, `email`. 24-hour token lifetime, no refresh token in v1.

**Health (R-HC)**

- **R-HC-1.** `GET /api/v1/health` returns `{ "status": "ok" }` after a `SELECT 1` ping. No auth required.

### 2.2 Cross-cutting requirements

- **R-X-1. API namespace.** All routes prefixed `/api/v1/`.
- **R-X-2. Error envelope.** All error responses use `{ "error": { "code": "<enum>", "message": "<english>", "details": {...} } }`. Codes: `not_found`, `validation_error`, `auth_required`, `forbidden`, `conflict`, `internal_error`.
- **R-X-3. CORS.** Allow-listed origins from `CORS_ORIGINS` env (comma-separated). Default local: `http://localhost:3000`. No wildcard.
- **R-X-4. Logging.** Structured JSON to stdout. Each request line includes `request_id`, `path`, `method`, `status`, `latency_ms`. `request_id` from `X-Request-Id` header if present, else generated. CloudWatch ingests stdout natively.
- **R-X-5. No silent substitution.** Invalid IDs always `404`; never substitute a similar entity.
- **R-X-6. Performance.** Common reads under 1s; all reads under 5s.

### 2.3 Documented v1 gaps

These are intentional v1 limitations with a clear upgrade path. They are **not** bugs; the design records them so they don't get re-litigated.

- **G-1. Rate limiting.** Not enforced. Push to API Gateway throttling once traffic exists.
- **G-2. Pagination.** Not implemented. `shared/pagination.py` exists as a `Page[T]` scaffold but no endpoint uses it.
- **G-3. Reputation behavior.** `users.reputation_score` defaults to 0 and is never mutated by v1 logic. `user_reputation_events` is deferred.
- **G-4. Anonymous-report abuse protection.** None. IP captured opportunistically for future moderation.
- **G-5. RDS Proxy / connection pooling.** Plain `pool_size=1, max_overflow=1`. Upgrade to RDS Proxy when concurrent invocations push toward Postgres `max_connections`.
- **G-6. Refresh tokens / token revocation.** Not in v1. Leaked token valid until `exp` (24h).
- **G-7. Background `abandoned`-trip sweep.** Enum value present; sweep job not implemented.
- **G-8. `Alert.time` formatting.** Backend ships ISO `emittedAt`; frontend computes the relative `time` string client-side. **Frontend coordination required:** `TransitPulseWebsite/src/types/transit.ts` `Alert` type currently has `time: string` and no `emittedAt`. The frontend must add `emittedAt: string` to the `Alert` type (and either keep `time` as a derived field or drop it). This is a known frontend task that lands in the same release as the backend.
- **G-9. Seed coupling.** New stops/alerts require both a backend seed entry and a matching frontend `I18N` entry.
- **G-10. Seed accuracy.** Headways and operator-route mappings are best-effort from public schedule pages; v1 seed is *plausible synthetic data*, not GTFS-accurate.
- **G-11. Arrival notes deferred.** `arrival.note_es` / `note_en` are always `null` in v1. Inline alert text on arrivals would require either the backend owning translations (duplicating the frontend `I18N` table) or a wire-format contract change. Deferred until that's worth doing.
- **G-12. Cross-template `/start` cancels the previous trip.** Q3.1 is enforced as "single active session"; switching to a different `tripId` cancels the previous in-progress trip without an explicit cancel call. Documented as a UX choice, not a contract requirement.

---

## 3. Architecture Overview

### 3.1 System shape

```mermaid
flowchart LR
    User[Browser]
    FE[Next.js Frontend<br/>API providers]
    APIGW[API Gateway<br/>HTTP API v2]
    Lambda[Lambda Container<br/>FastAPI + uvicorn :8080]
    LWA[Lambda Web Adapter<br/>extension binary]
    PG[(PostgreSQL 16)]

    User -->|HTTPS| FE
    FE -->|HTTPS /api/v1/*| APIGW
    APIGW -->|invoke| LWA
    LWA -->|HTTP localhost:8080| Lambda
    Lambda -->|TCP 5432| PG
```

In production, the Lambda function is a container image stored in ECR. API Gateway integration is `AWS_PROXY` to the function. The Web Adapter extension translates Lambda invocation events ↔ HTTP requests against the in-container uvicorn process.

### 3.2 Local development topology

```mermaid
flowchart LR
    Dev[Developer Browser<br/>localhost:3000]
    FE[Next.js Dev Server<br/>localhost:3000]
    Compose([docker-compose.yml])
    BE[backend container<br/>:8080]
    PG[(postgres container<br/>:5432)]

    Dev --> FE
    FE -->|/api/v1/*| BE
    Compose --> BE
    Compose --> PG
    BE -->|TCP| PG
```

The same container image runs locally as in Lambda. Locally, `AWS_LAMBDA_RUNTIME_API` is unset and the Web Adapter binary is dormant — uvicorn serves HTTP directly.

### 3.3 Request flow (planner search example)

```mermaid
sequenceDiagram
    autonumber
    participant FE as Frontend Provider
    participant GW as API Gateway
    participant LWA as Web Adapter
    participant App as FastAPI App
    participant SVC as PlannerService
    participant DB as Postgres

    FE->>GW: GET /api/v1/planner/search?from=Heredia&to=San+Pedro&sort=fastest
    GW->>LWA: Lambda invoke (HTTP event)
    LWA->>App: GET /api/v1/planner/search ...
    App->>App: Middleware: request_id, JSON log
    App->>SVC: search(from, to, sort)
    SVC->>DB: resolve_endpoints(from) — pg_trgm + Haversine
    SVC->>DB: resolve_endpoints(to)
    SVC->>DB: walk_routes(origin_id, dest_id) — direct + 1-transfer
    SVC->>DB: upsert trip_templates (content hash)
    SVC-->>App: TripOption[]
    App-->>LWA: 200 + JSON body
    LWA-->>GW: Lambda response
    GW-->>FE: 200 OK
```

### 3.4 Backend module layout

```mermaid
flowchart TB
    subgraph backend/app
        main[main.py<br/>app factory + middleware wiring]
        config[config.py<br/>Pydantic Settings]
        db[db.py<br/>engine + session factory]
        deps[dependencies.py<br/>get_db, get_current_user]
        subgraph modules
            planner[planner/]
            stops[stops/]
            arrivals[arrivals/]
            alerts[alerts/]
            reports[reports/]
            users[users/]
            auth[auth/]
            health[health/]
            shared[shared/<br/>exceptions, pagination,<br/>security, types, logging]
        end
        models[models/<br/>SQLAlchemy mappings]
        seed[seed/<br/>JSON fixtures + loader]
    end

    main --> config
    main --> db
    main --> deps
    main --> modules
    modules --> models
    seed --> models
```

Each feature module owns three files: `router.py` (FastAPI routes), `service.py` (business logic, takes a session), `schemas.py` (Pydantic request/response models). `models/` holds SQLAlchemy ORM classes shared across modules. `shared/` holds cross-cutting helpers.

---

## 4. Components and Interfaces

### 4.1 Module responsibilities

| Module | HTTP routes | Service responsibilities |
|---|---|---|
| `planner` | `GET /search`, `GET /trips/{id}`, `POST /trips/{id}/start`, `POST /trips/{id}/advance` | Resolve `from`/`to`, walk route graph, persist `trip_templates`, manage `active_trips` lifecycle |
| `stops` | `GET /stops`, `GET /stops/{id}` | List + detail; optional Haversine `dist` |
| `arrivals` | `GET /arrivals/home`, `GET /arrivals/stops/{id}` | Compute upcoming arrivals from `arrival_schedules` |
| `alerts` | `GET /alerts` (with optional `?routeIds=`) | Filter active alerts by route overlap |
| `reports` | `POST /reports` | Persist user reports with derived metadata |
| `users` | `GET /users/me` | Current user profile |
| `auth` | `POST /auth/register`, `POST /auth/login` | Account creation, password verification, JWT issuance |
| `health` | `GET /health` | DB ping; no business deps |
| `shared` | (no routes) | Exceptions, pagination scaffold, JWT helpers, logging config, Haversine helper, `pg_trgm` query helpers |

### 4.2 Cross-cutting components

#### 4.2.1 App factory (`app/main.py`)

Builds a `FastAPI()` instance, wires CORS middleware, request-ID + logging middleware, the global exception handler, includes each module's router, and exposes `app` as the ASGI callable for uvicorn.

```python
def create_app() -> FastAPI:
    app = FastAPI(title="TransitPulse Backend", version="1.0.0")
    configure_logging()
    add_middleware(app)              # CORS, request_id, access log
    add_exception_handlers(app)      # AppError → envelope
    app.include_router(planner.router, prefix="/api/v1/planner")
    app.include_router(stops.router,   prefix="/api/v1/stops")
    # ...etc
    return app

app = create_app()
```

#### 4.2.2 Settings (`app/config.py`)

Pydantic `BaseSettings` reading from environment:

| Setting | Type | Default | Notes |
|---|---|---|---|
| `database_url` | str | — | Required. `postgresql+psycopg://...` |
| `jwt_secret` | str | — | Required. ≥32 bytes |
| `jwt_expires_seconds` | int | `86400` | 24h |
| `cors_origins` | list[str] | `["http://localhost:3000"]` | Comma-split |
| `log_level` | str | `"INFO"` |  |
| `arrivals_home_limit` | int | `6` | R-AR-1 |
| `nearest_stop_radius_m` | float | `2000.0` | R-PL-2 |
| `fuzzy_threshold` | float | `0.3` | `pg_trgm` similarity floor |

#### 4.2.3 DB layer (`app/db.py`)

```python
engine = create_engine(
    settings.database_url,
    pool_size=1, max_overflow=1,
    pool_pre_ping=True, pool_recycle=600,
    future=True,
)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
```

Engine is module-level so warm Lambda invocations reuse the connection across calls.

#### 4.2.4 Dependencies (`app/dependencies.py`)

```python
def get_db() -> Iterator[Session]:
    with SessionLocal() as session:
        yield session

def get_current_user(token: Annotated[str | None, Depends(bearer_scheme)] = None,
                    session: Session = Depends(get_db)) -> User:
    # Decode JWT, raise AuthRequired if missing/invalid

def get_current_user_optional(...) -> User | None:
    # Same, but returns None instead of raising — used by endpoints
    # that accept both auth and anonymous (planner /start, reports POST)
```

#### 4.2.5 Exception handling (`shared/exceptions.py`)

```python
class AppError(Exception):
    code: str
    http_status: int
    message: str
    details: dict | None = None

class NotFoundError(AppError):    code, http_status = "not_found", 404
class ValidationError(AppError):  code, http_status = "validation_error", 422
class AuthRequiredError(AppError):code, http_status = "auth_required", 401
class ForbiddenError(AppError):   code, http_status = "forbidden", 403
class ConflictError(AppError):    code, http_status = "conflict", 409
```

A FastAPI exception handler converts `AppError` and `RequestValidationError` into the R-X-2 envelope.

#### 4.2.6 Logging (`shared/logging.py`)

JSON formatter; middleware sets `request.state.request_id`, emits one access-log record per request with `request_id`, `path`, `method`, `status`, `latency_ms`. Service-level logs are also JSON, child loggers per module.

### 4.3 Service-layer interfaces

**`PlannerService`** (annotated signatures, not full code):

```python
class PlannerService:
    def __init__(self, session: Session): ...

    def search(self, from_: str, to: str, sort: SortMode) -> list[TripOption]:
        """R-PL-1..7. Resolve, graph-walk, persist, sort, decorate."""

    def get_trip_detail(self, trip_id: str) -> TripDetailDto:
        """R-PL-8. Raises NotFoundError on miss."""

    def start_trip(self, trip_id: str, user: User | None) -> ActiveTripDto:
        """R-PL-9. Idempotent re-start for authenticated users."""

    def advance_trip(self, trip_id: str, current_step_index: int,
                     active_trip_id: str | None, user: User | None) -> ActiveTripDto:
        """R-PL-10..11. Auto-completes on final step."""
```

**`StopsService`**:

```python
def list_stops(self, lat: float | None, lng: float | None) -> list[Stop]: ...
def get_stop(self, stop_id: str) -> StopDetailDto: ...   # raises NotFoundError
```

**`ArrivalsService`**:

```python
def home_arrivals(self, limit: int = 6) -> list[Arrival]: ...
def arrivals_for_stop(self, stop_id: str) -> list[Arrival]: ...   # raises NotFoundError on unknown stop
```

**`AlertsService`**:

```python
def list_active(self, route_ids: list[str] | None = None) -> list[Alert]: ...
```

**`ReportsService`**:

```python
def submit(self, payload: ReportSubmissionDto, user: User | None,
           source_ip: str | None) -> ReportCreatedDto: ...
```

**`AuthService`**:

```python
def register(self, payload: RegisterDto) -> User: ...     # raises ConflictError on duplicate email
def login(self, payload: LoginDto) -> TokenDto: ...       # raises AuthRequiredError on bad creds
```

**`UsersService`**:

```python
def me(self, user: User) -> UserProfileDto: ...
```

### 4.4 Endpoint catalog (full)

| Method | Path | Auth | Returns | Errors |
|---|---|---|---|---|
| GET | `/api/v1/health` | — | `{ status }` | — |
| GET | `/api/v1/planner/search` | optional | `TripOption[]` | `validation_error` |
| GET | `/api/v1/planner/trips/{tripId}` | optional | `TripDetailDto` | `not_found` |
| POST | `/api/v1/planner/trips/{tripId}/start` | optional | `ActiveTripDto` | `not_found` |
| POST | `/api/v1/planner/trips/{tripId}/advance` | optional | `ActiveTripDto` | `not_found`, `validation_error` |
| GET | `/api/v1/stops` | — | `Stop[]` | `validation_error` (bad lat/lng) |
| GET | `/api/v1/stops/{stopId}` | — | `StopDetailDto` | `not_found` |
| GET | `/api/v1/arrivals/home` | — | `Arrival[]` | — |
| GET | `/api/v1/arrivals/stops/{stopId}` | — | `Arrival[]` | `not_found` |
| GET | `/api/v1/alerts` | — | `Alert[]` | — |
| POST | `/api/v1/reports` | optional | `ReportCreatedDto` | `validation_error` |
| POST | `/api/v1/auth/register` | — | `UserProfileDto` | `conflict`, `validation_error` |
| POST | `/api/v1/auth/login` | — | `TokenDto` | `auth_required`, `validation_error` |
| GET | `/api/v1/users/me` | required | `UserProfileDto` | `auth_required` |

---

## 5. Data Models

### 5.1 ER diagram

```mermaid
erDiagram
    users ||--o{ reports : "submits"
    users ||--o{ active_trips : "owns (nullable)"
    routes ||--o{ route_stops : "ordered"
    stops ||--o{ route_stops : "served by"
    routes ||--o{ arrival_schedules : "schedule"
    stops ||--o{ arrival_schedules : "schedule"
    routes ||--o{ alert_routes : "tags"
    alerts ||--o{ alert_routes : "tags"
    trip_templates ||--o{ active_trips : "instances"
    active_trips ||--o{ active_trip_steps : "ordered steps"

    users {
        uuid id PK
        text email UK
        text password_hash
        text display_name
        timestamptz created_at
        int reputation_score
        bool is_active
    }
    routes {
        text id PK
        text short_name
        text long_name
        text mode
        int fare_min
        int fare_max
        text color
    }
    stops {
        text id PK
        text name_key
        text addr_key
        double lat
        double lng
        bool live
    }
    route_stops {
        text route_id FK
        text stop_id FK
        int stop_order
    }
    arrival_schedules {
        bigserial id PK
        text route_id FK
        text stop_id FK
        smallint weekday
        time first_service
        time last_service
        smallint headway_minutes
        text dest_es
        text dest_en
    }
    alerts {
        text id PK
        text severity
        text title_key
        text body_key
        timestamptz emitted_at
        bool is_active
    }
    alert_routes {
        text alert_id FK
        text route_id FK
    }
    places {
        text id PK
        text label_es
        text label_en
        text near_stop_id FK
    }
    trip_templates {
        text id PK
        text origin_stop_id FK
        text destination_stop_id FK
        text content_hash UK
        int total_minutes
        int total_price
        int transfers
        int walk_min
        jsonb steps
        timestamptz created_at
    }
    active_trips {
        bigserial id PK
        text active_trip_id UK
        text trip_id FK
        uuid user_id FK
        smallint current_step_index
        text status
        timestamptz started_at
        timestamptz updated_at
    }
    active_trip_steps {
        bigserial id PK
        bigint active_trip_id FK
        smallint step_index
        text kind
        text route
        text time_label
        smallint minutes
        jsonb payload
    }
    reports {
        bigserial id PK
        uuid user_id FK
        text route_id FK
        text stop_id FK
        text type
        text description
        text status
        inet source_ip
        timestamptz created_at
    }
```

### 5.2 Table-level notes

- **`users.id`** is a UUID v4 generated server-side. `email` is unique, lower-cased on insert. `reputation_score` defaults to 0 and is never mutated by v1 (G-3).
- **`routes.id`** is the public route code (e.g., `"400"`, `"400A"`, `"T1"`). Mode ∈ `{bus, train}`. Fares in CRC integers (avoid floats).
- **`stops.id`** is a stable string (`"s1"`, `"s2"`, …) matching the frontend mock. `name_key`/`addr_key` are i18n keys (must exist in frontend `I18N`). `live` flips arrivals participation.
- **`route_stops`** PK is `(route_id, stop_id)`, `stop_order` defines direction.
- **`arrival_schedules`** denormalizes destination text per `(route_id, stop_id)` so arrival rows can populate `destEs/destEn` without an extra join. `weekday` ∈ `0..6` (Mon=0). `headway_minutes` is the typical interval between buses for that day.
- **`alerts.title_key`/`body_key`** are i18n keys (G-9). `alert_routes` is the route filter join table for R-AL-2.
- **`places`** powers free-text fuzzy match for landmarks/neighborhoods. `near_stop_id` is the stop a free-text hit resolves to.
- **`trip_templates.content_hash`** is `sha256("{origin_stop_id}|{destination_stop_id}|{steps_signature}")`, where `steps_signature` = `';'.join("{step.kind}:{step.route or ''}:{step.from_stop_id or ''}:{step.to_stop_id or ''}" for step in steps)`. Including `from`/`to` stop IDs per step is what distinguishes two single-transfer itineraries that use the same route pair but transfer at different stops. Unique constraint enables R-PL-5 dedup via `INSERT ... ON CONFLICT DO NOTHING RETURNING`.
- **`trip_templates.id`** is generated server-side as `tt_<base32(uuid4)[:10]>` (e.g., `tt_3xb7q9zk1a`). Short, opaque, URL-safe. Generated at the moment of upsert; if the row already exists by `content_hash`, the existing `id` is returned by the `RETURNING` clause.
- **`trip_templates.steps`** is a `jsonb` column holding the discriminated union (walk/bus/transfer) with bilingual fields. Storing it denormalized keeps `GET /trips/{id}` a single-row read.
- **`active_trips.active_trip_id`** is a public-facing opaque UUID (the wire `activeTripId`). `id` (bigserial) is internal. Status enum: `in_progress | completed | cancelled | abandoned` (G-7).
- **`active_trip_steps`** mirrors `trip_templates.steps` row-form for query convenience; in v1 it is populated by copying from the `jsonb` at start time. `payload` carries the kind-specific bilingual fields verbatim.
- **`reports.source_ip`** is `inet`. `type` and `status` are text-with-CHECK rather than Postgres enums (cheaper to evolve). Type ∈ `{delay, breakdown, accident, overcrowding, route_change, safety, other}`. Status ∈ `{new, confirmed, dismissed, resolved}`, default `new`.

### 5.3 Indexes

- `stops` — GIN on `name_key gin_trgm_ops` for fuzzy match (R-PL-2). B-tree on `(lat, lng)` is unnecessary at v1 scale (~30 rows).
- `routes` — GIN on `long_name gin_trgm_ops`.
- `places` — GIN on `label_es gin_trgm_ops` and on `label_en gin_trgm_ops`.
- `trip_templates` — UNIQUE on `content_hash`.
- `active_trips` — UNIQUE on `active_trip_id`. Partial index on `(user_id, trip_id) WHERE status = 'in_progress'` for R-PL-9 idempotency lookup.
- `arrival_schedules` — `(route_id, stop_id, weekday)`.
- `alerts` — partial `WHERE is_active = true`.
- `alert_routes` — composite PK `(alert_id, route_id)` and a separate `(route_id)` index for filter queries.

### 5.4 Pydantic schema sketch (response side, mirroring contracts)

```python
# stops/schemas.py
class StopOut(BaseModel):
    id: str
    nameKey: str
    addrKey: str
    dist: int               # meters, computed
    live: bool
    routes: list[str]

# arrivals/schemas.py
class ArrivalOut(BaseModel):
    id: str
    route: str
    kind: Literal["bus", "train"]
    destEs: str
    destEn: str
    etaSec: int
    status: Literal["on-time","delayed","disrupted","unknown","ok","warn","bad"]
    occupancy: int          # 0..4
    note_es: str | None = None
    note_en: str | None = None

# planner/schemas.py
class WalkStepOut(BaseModel):
    kind: Literal["walk"] = "walk"
    minutes: int
    toEs: str
    toEn: str
    time: str

class BusStepOut(BaseModel):
    kind: Literal["bus"] = "bus"
    route: str
    minutes: int
    fromEs: str
    fromEn: str
    toEs: str
    toEn: str
    time: str
    occ: int
    stops: int

class TransferStepOut(BaseModel):
    kind: Literal["transfer"] = "transfer"
    minutes: int
    toEs: str
    toEn: str
    time: str

TripStepOut = Annotated[
    WalkStepOut | BusStepOut | TransferStepOut,
    Field(discriminator="kind"),
]

class TripOptionOut(BaseModel):
    id: str
    tag: Literal["fastest","cheapest","fewest"]
    minutes: int
    price: int
    transfers: int
    walkMin: int
    leaveIn: int
    confidence: float
    occupancy: int
    steps: list[TripStepOut]

class TripDetailOut(BaseModel):
    id: str
    minutes: int
    price: int
    transfers: int
    walkMin: int
    leaveIn: int
    confidence: float
    occupancy: int
    steps: list[TripStepOut]

class ActiveTripOut(BaseModel):
    tripId: str
    activeTripId: str         # added per Q14.C2
    currentStepIndex: int
    steps: list[TripStepOut]
    etaMinutes: int
    started: int              # epoch ms

# alerts/schemas.py
class AlertOut(BaseModel):
    id: str
    severity: Literal["bad","warn","ok"]
    titleKey: str
    bodyKey: str
    emittedAt: str            # ISO 8601 (G-8)
    routes: list[str]
```

Request schemas mirror canonical inputs:

```python
class TripAdvanceIn(BaseModel):
    currentStepIndex: int = Field(ge=0)
    activeTripId: str | None = None

class ReportSubmitIn(BaseModel):
    type: Literal["delay","breakdown","accident","overcrowding","route_change","safety","other"]
    routeId: str | None = None
    stopId: str | None = None
    description: str = Field(min_length=1, max_length=2000)

class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    displayName: str = Field(min_length=1, max_length=64)

class LoginIn(BaseModel):
    email: EmailStr
    password: str
```

### 5.5 Planner algorithm

Pseudocode for the core search loop (R-PL-2..6):

```python
def search(from_str, to_str, sort):
    origin = resolve_endpoint(from_str)        # may be None
    dest   = resolve_endpoint(to_str)
    if origin is None or dest is None:
        return []                               # R-PL-3

    candidates = []
    # 1) Direct: any route serving both origin and dest in correct order
    for route in routes_through(origin, dest):
        candidates.append(direct_option(route, origin, dest))

    # 2) Single transfer: for each transfer-stop S where route A serves
    #    (origin -> S) and route B serves (S -> dest)
    for (route_a, route_b, transfer_stop) in transfer_pairs(origin, dest):
        candidates.append(transfer_option(route_a, route_b, transfer_stop, origin, dest))

    sorted_candidates = sort_options(candidates, sort)

    # 3) Persist + tag
    out = []
    for opt in sorted_candidates:
        trip_id = upsert_template(opt)         # ON CONFLICT DO NOTHING RETURNING
        opt.id = trip_id
        opt.tag = sort
        opt.confidence = compute_confidence(opt)
        opt.occupancy = compute_occupancy(opt)
        out.append(opt)
    return out
```

`resolve_endpoint(s)`:

```python
def resolve_endpoint(s):
    if is_lat_lng(s):
        lat, lng = parse(s)
        return nearest_stop_within(lat, lng, settings.nearest_stop_radius_m)
    # Free text: fuzzy match across stop names, route long_names, places
    return fuzzy_resolve(s)  # SELECT ... ORDER BY similarity(...) DESC LIMIT 1
```

The graph walk is brute-force at v1 scale (~5 routes, ~30 stops); no Dijkstra/A*. Step minutes are taken from `route_stops.stop_order` deltas using a per-route average minutes-per-stop (seeded with the route).

### 5.6 Active trip lifecycle

```mermaid
stateDiagram-v2
    [*] --> in_progress : start
    in_progress --> in_progress : advance (not final step)
    in_progress --> completed : advance (final step)
    in_progress --> cancelled : (future, manual)
    in_progress --> abandoned : (future, sweep job — G-7)
    completed --> [*]
    cancelled --> [*]
    abandoned --> [*]
```

For `start`:

- Authenticated + existing in-progress trip on same `tripId` → return existing (idempotent).
- Authenticated + no existing → create.
- Anonymous → always create. Backend issues a fresh `activeTripId` (UUID v4).

For `advance`:

- Resolve target active trip:
  - Authenticated, no `activeTripId` in body → lookup `(user_id, tripId)` with `status=in_progress`. → `404` if none.
  - `activeTripId` provided → lookup directly. → `404` if not found or `tripId` doesn't match.
- Compute `next = min(currentStepIndex + 1, len(steps) - 1)`.
- If `next == len(steps) - 1`, transition status to `completed`.
- Update `current_step_index`, `updated_at`, return DTO.

---

## 6. Error Handling

### 6.1 Envelope (R-X-2)

```json
{
  "error": {
    "code": "not_found",
    "message": "Trip not found",
    "details": { "tripId": "tt_abc123" }
  }
}
```

`details` is optional. `message` is always English (per Q5/Q14). `code` is one of:

| Code | HTTP | Use |
|---|---|---|
| `not_found` | 404 | Unknown ID for any resource |
| `validation_error` | 422 | Pydantic validation failure or business rule |
| `auth_required` | 401 | Missing/invalid bearer token, bad credentials |
| `forbidden` | 403 | Authenticated but not allowed (rare in v1) |
| `conflict` | 409 | Unique-constraint conflict (e.g., duplicate email) |
| `internal_error` | 500 | Unhandled exception; details omitted |

### 6.2 Exception flow

1. Service layer raises a subclass of `AppError` (`NotFoundError`, `ConflictError`, …).
2. Pydantic raises `RequestValidationError` automatically on bad inputs.
3. The global handlers convert both into the envelope shape and the right HTTP status.
4. `Exception` (anything unhandled) becomes `internal_error`, logged with the stack trace and the `request_id`.

### 6.3 Logging on errors

Every error path logs a JSON line with:
- `request_id`, `path`, `method`
- `code`, `http_status`
- `message`
- `exception` (full traceback) for `internal_error` only
- `user_id` if available

This means a `request_id` returned to the client can be matched against CloudWatch logs deterministically.

---

## 7. Testing Strategy

### 7.1 Test pyramid

```mermaid
flowchart TB
    contract[Contract tests<br/>~10 — schema parity with frontend types]
    api[API tests<br/>~30 — TestClient against full app]
    unit[Unit tests<br/>~50 — services, helpers, Pydantic validators]

    contract --> api --> unit
```

### 7.2 Test database

- Single `transitpulse_test` database on the same Postgres container as dev (Q9).
- A session-scoped fixture creates the schema once via Alembic, installs `pg_trgm`, and loads seed.
- A function-scoped fixture opens a transaction, hands a `Session` to the test, and rolls back on teardown.
- The DI override replaces `get_db` with the test session so the `TestClient` requests share the same transaction.

```python
@pytest.fixture(scope="session")
def setup_db():
    run_alembic_upgrade("head", database_url=TEST_DATABASE_URL)
    load_seed(TEST_DATABASE_URL)
    yield

@pytest.fixture
def db_session(setup_db):
    connection = engine.connect()
    transaction = connection.begin()
    session = SessionLocal(bind=connection)
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()

@pytest.fixture
def client(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
```

### 7.3 Unit tests (services + helpers)

- `compute_confidence` / `compute_occupancy` — pure-function tests with edge values.
- `parse_lat_lng` — valid/invalid coordinate strings.
- `fuzzy_resolve` — given seeded `places`/`stops`/`routes`, asserts expected resolution; uses real `pg_trgm`.
- `walk_routes` — direct and one-transfer cases on a small fixture graph.
- JWT `encode`/`decode` — round-trip; expired token rejection.
- Password hashing helpers — verify-after-hash; reject-wrong-password.
- `compute_arrival_eta_seconds` — given a schedule row + current time, returns the expected ETA.

### 7.4 API tests (one per endpoint, plus error paths)

Required by spec §17 plus defaults:

- `GET /search` returns valid `TripOption[]` for known origin/dest; empty for unresolvable input (R-PL-3).
- `GET /trips/{id}` → `404` for unknown id; `200` for known id with stable shape.
- `POST /start` → `200`; idempotent re-start returns same `activeTripId` for authenticated user.
- `POST /advance` → `404` for unknown trip; `400 validation_error` for anonymous-without-`activeTripId`; `200` for valid; auto-completes on final step.
- `GET /stops` → with and without `lat,lng`; `dist` is non-zero only when params are supplied.
- `GET /stops/{id}` → `404` for unknown id.
- `GET /arrivals/home` → returns N=6 ordered ascending by ETA.
- `GET /arrivals/stops/{id}` → `404` for unknown stop.
- `GET /alerts?routeIds=...` → returns only alerts overlapping the supplied routes.
- `POST /reports` → `201`; both anonymous and authenticated paths.
- `POST /auth/register` + `/login` + `/users/me` round-trip works.
- `GET /users/me` without bearer → `401`.

### 7.5 Contract tests

Snapshot the JSON shape returned by each endpoint and assert keys + types match the canonical TypeScript contract types. The snapshots are stored in `tests/snapshots/`; updates require a deliberate `--snapshot-update` flag.

A separate guardrail test parses the frontend `I18N.es` table (loaded as a frozen JSON snapshot in `tests/fixtures/frontend_i18n.json`) and asserts that every seeded `nameKey`, `addrKey`, `titleKey`, and `bodyKey` exists as a key in that snapshot. Catches the G-9 coupling at CI time.

### 7.6 What's not tested in v1

- Lambda packaging itself (smoke-tested via `docker compose up` only).
- End-to-end against real API Gateway (CI smoke test deferred).
- Performance/load tests (out of scope; spec §14 budgets are checked manually).

---

## 8. Local Development

### 8.1 `docker-compose.yml` shape

```yaml
services:
  postgres:
    image: postgres:16
    environment:
      POSTGRES_DB: transitpulse
      POSTGRES_USER: transitpulse
      POSTGRES_PASSWORD: transitpulse
    ports: ["5432:5432"]
    volumes: ["pgdata:/var/lib/postgresql/data"]
    healthcheck:
      test: ["CMD", "pg_isready", "-U", "transitpulse"]
      interval: 3s

  backend:
    build: ./backend
    depends_on:
      postgres: { condition: service_healthy }
    environment:
      DATABASE_URL: postgresql+psycopg://transitpulse:transitpulse@postgres:5432/transitpulse
      JWT_SECRET: dev-only-secret-change-me-32-bytes-min
      CORS_ORIGINS: http://localhost:3000
    ports: ["8080:8080"]

volumes:
  pgdata:
```

### 8.2 Developer workflow

```bash
docker compose up -d postgres
docker compose run --rm backend alembic upgrade head
docker compose run --rm backend python -m app.seed.load   # idempotent
docker compose up backend
# in another shell:
cd TransitPulseWebsite && npm run dev
```

The seed loader is idempotent: it inserts missing rows, leaves existing rows alone, and is safe to re-run.

### 8.3 `Dockerfile`

Per `research/lambda-web-adapter.md`:

```dockerfile
FROM public.ecr.aws/docker/library/python:3.12-slim

COPY --from=public.ecr.aws/awsguru/aws-lambda-adapter:1.0.0 \
  /lambda-adapter /opt/extensions/lambda-adapter

WORKDIR /var/task
COPY requirements.txt .
RUN python -m pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY migrations ./migrations
COPY alembic.ini .

EXPOSE 8080
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
```

The Web Adapter binary is dormant locally (no `AWS_LAMBDA_RUNTIME_API` env var) and active in Lambda. Same image, both environments.

---

## 9. Security

| Requirement | v1 implementation |
|---|---|
| HTTPS in production | API Gateway terminates TLS |
| Request validation | Pydantic at the API boundary |
| Hashed passwords | argon2 via `passlib` |
| JWT verification | HS256, 24h expiry, env-managed secret |
| Env-managed secrets | `JWT_SECRET`, `DATABASE_URL` from env (no Secrets Manager call in v1) |
| Backend-only external creds | No external integrations in v1; pattern reserved |
| Rate limiting | G-1 — deferred to API Gateway throttling |
| CORS | Allow-list only, no wildcard |

---

## 10. Migration path beyond v1

These are not v1 work, but the design preserves room for them:

- **Real transit feeds.** Adapters under `app/integrations/` per provider, called by `arrivals` and `alerts` services. No API contract change.
- **Geospatial queries.** `stops.lat/lng` exist; PostGIS optional later.
- **Reputation events.** Add `user_reputation_events` table; introduce moderator role; transition reports through `confirmed/dismissed/resolved`.
- **Caching.** ElastiCache + read-through cache on hot endpoints.
- **RDS Proxy.** Drop-in once concurrency demands it (G-5).
- **WebSockets.** Route `/api/v1/ws/...` through API Gateway WebSocket API; backend handles via a separate Lambda or a small ASGI worker.

---

## 11. Appendices

### 11.A Technology choices with pros and cons

| Choice | Picked | Pros | Cons | Alternative considered |
|---|---|---|---|---|
| Web framework | FastAPI | OpenAPI built-in, Pydantic v2 validation, ASGI-native, great DX | New-ish ecosystem vs Django | Django/DRF (more boilerplate, sync-first), Starlette raw (too low-level) |
| Lambda packaging | AWS Lambda Web Adapter + container | Same image local + prod, no handler code, normal uvicorn | Cold-start cost | Mangum (smaller, but local/prod asymmetry) |
| API Gateway flavor | HTTP API (v2) | Cheaper, faster, sufficient for JSON | Fewer integrations than REST API | REST API (v1) — overkill |
| ORM | SQLAlchemy 2.x | Mature, typed, Alembic integration | Verbose vs simpler ORMs | SQLModel (younger, less battle-tested), psycopg-only (no migrations story) |
| DB pool | `pool_size=1, max_overflow=1` | Minimal Lambda concurrency footprint | Connection storm risk under burst | RDS Proxy (managed pooling, $$ + extra service) |
| i18n strategy | Mixed (keys + inline) | Honors existing frontend contract literally | Tight coupling for stops/alerts | Inline everywhere (R2) — would need frontend refactor |
| Test DB | Compose Postgres + transactional rollback | Fast, real Postgres, no extra infra | No isolation between test runs if a test commits | Testcontainers (more deps), pytest-postgresql (system Postgres binary), SQLite (breaks pg_trgm) |
| Auth UX | Email + password | Simplest; matches `password_hash` schema | Weaker DX than magic link | Magic link (needs SMTP/SES) |
| JWT signing | HS256 + single secret | Cheap, common | Symmetric — can't expose public verify key | RS256 (extra key mgmt) |
| Rate limiting | None (deferred) | No infra cost; honest about gap | No abuse protection in v1 | In-process counter (misleading on Lambda), Redis (excluded by spec) |

### 11.B Existing solutions analysis

- **Frontend mock providers** under `TransitPulseWebsite/src/data/providers/mock/` are reference implementations for behavior the backend must replicate. Behavior catalogued in `research/frontend-providers.md`. Key implication: `etaMinutes` on `ActiveTripDto` is *remaining* time, not total.
- **Frontend `I18N` table** in `TransitPulseWebsite/src/data/transit.ts` is the source of truth for stop/alert key translations. The backend never owns these strings; it only ships keys.
- **Public CTP / Moovit data** for GAM routes is only loose reference. v1 seed is plausible synthetic data, not GTFS-accurate.

### 11.C Alternative approaches considered (and why rejected)

- **Pre-baked trip templates (Q2.B / Q2.C).** Forces hand-curating every (origin, destination) pair into seed; doesn't scale even at 30 stops; rejected.
- **Stop-ID-only planner input (Q1.A).** Fails the "search 'Heredia'" UX; rejected.
- **Disallow anonymous active trips (Q3 / Q4.D).** Contradicts spec's "auth optional"; rejected.
- **Wildcard CORS (Q10).** Easier but unsafe; rejected.
- **Pre-formatted `Alert.time` server-side.** Locale-sensitive, brittle; rejected in favor of ISO `emittedAt`.
- **Magic-link auth (Q6.B).** Adds email-sending dependency for v1; rejected.
- **In-process rate limiting.** On Lambda each container has its own counter; misleading; rejected.

### 11.D Key constraints & limitations identified during research

- **Spec/contract conflicts (5).** The contract files differ from the spec on i18n shape (stops, alerts), `ActiveTripDto` field set, `Alert.time`, `Stop.dist`, and `confidence`/`occupancy` (not in spec). All resolved in Q14.
- **Frontend `I18N` coupling.** Stops and alerts cannot be added without a frontend release. Documented as G-9.
- **No public GTFS feed for GAM.** Seed is synthetic. Documented as G-10.
- **Lambda cold starts.** Acceptable trade-off for image parity. No mitigation in v1.
- **Postgres `max_connections` under high concurrent Lambda.** Documented as G-5; RDS Proxy is the upgrade path.

### 11.E Glossary

- **Active trip** — a user's in-progress trip session, addressable by `activeTripId`. Tracks `currentStepIndex` and `status`.
- **Trip template** — the persisted, hashable representation of a single search-result option (`trip_templates` row). Provides a stable `tripId`.
- **GAM** — Gran Área Metropolitana, the Costa Rican greater metropolitan region.
- **i18n key** — a string identifier (e.g., `"stop_1"`) the frontend resolves to display text via its `I18N` table.
- **Lambda Web Adapter** — AWS-published binary loaded as a Lambda extension that translates Lambda invocation events ↔ HTTP requests, letting normal web servers run on Lambda unchanged.
- **Modular monolith** — single deployable artifact with clear module boundaries; not microservices.
