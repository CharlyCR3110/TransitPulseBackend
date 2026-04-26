# TransitPulse Backend Final Specification

## 1. Purpose

This is the canonical backend specification for TransitPulse v1.

It replaces conflicting assumptions from earlier documents and aligns the backend with:

- the current frontend contracts in `TransitPulseWebsite/src/data/contracts/`
- the product requirements in `docs/01_requirements_documentation (1).docx`
- the architecture guidance in `docs/02_arquitectura.docx`
- the implementation reality of the current frontend slice

This document is the source of truth for backend scope, module boundaries, API shape, persistence, and deployment approach.

## 2. Final Decisions

The following decisions are locked for v1:

- Deployment target: AWS Lambda, exposed through API Gateway
- Local development model: Docker-based local stack that simulates the backend environment
- Backend style: modular monolith, not microservices
- Primary datastore: PostgreSQL only
- Cache: no Redis in v1
- Queue/background system: none in v1
- Active trip ownership: backend-owned
- External data strategy: seed data first, live integrations later through adapters
- Users: included in v1 because crowdsourced reports need identity and reputation context
- Payments: excluded from v1

## 3. Goals of v1

The backend must support one useful product slice end to end:

- search trips
- inspect trip detail
- start and advance an active trip
- inspect stops and arrivals
- read alerts
- submit user reports
- support a basic user account for crowdsourcing participation

The backend does not need to solve the full long-term platform vision in v1.

## 4. Non-Goals for v1

These are explicitly out of scope:

- digital payments
- subscriptions
- favorites/history-heavy personalization
- real ML training pipeline in production
- Redis caching
- WebSockets
- background workers
- full GTFS-grade routing engine
- multi-region deployment
- advanced moderation system

## 5. Architecture

### 5.1 System shape

TransitPulse uses a separated frontend and backend architecture:

- Frontend: Next.js web application
- Backend: Python FastAPI application packaged for Lambda
- Database: PostgreSQL
- External services: maps, transport feeds, weather, and similar providers are consumed only by the backend

### 5.2 Backend style

The backend is a modular monolith:

- one codebase
- one deployable application artifact
- feature modules with clear ownership

This keeps implementation cost lower than microservices while preserving maintainability.

### 5.3 Deployment model

Production:

- API Gateway
- AWS Lambda
- PostgreSQL database

Local development:

- Docker Compose
- local backend container
- local PostgreSQL container

Important clarification:

Local development does not need to emulate Lambda perfectly at the infrastructure level. It only needs to preserve behavior that matters to development:

- stateless request handling
- environment-based configuration
- API shape parity
- database-backed flows

## 6. Technology Stack

### 6.1 API framework

- Python 3.12
- FastAPI
- Pydantic v2

Reasoning:

- strong request/response validation
- OpenAPI generation
- clean modular structure
- good fit for prediction logic later

### 6.2 Persistence

- PostgreSQL 16
- SQLAlchemy 2.x
- Alembic migrations

PostgreSQL is the only required datastore in v1.

### 6.3 Authentication

Users are included in v1, but authentication should stay lightweight:

- email/password or magic-link style auth are both acceptable
- JWT-based stateless auth is the default recommendation
- anonymous report submission may still exist, but authenticated users should be the primary path

The exact auth UX can be finalized later without changing the domain model.

## 7. Repository Layout

The backend should live in a new top-level `backend/` directory:

```text
backend/
  app/
    main.py
    config.py
    db.py
    dependencies.py
    modules/
      planner/
        router.py
        service.py
        schemas.py
      stops/
        router.py
        service.py
        schemas.py
      arrivals/
        router.py
        service.py
        schemas.py
      alerts/
        router.py
        service.py
        schemas.py
      reports/
        router.py
        service.py
        schemas.py
      users/
        router.py
        service.py
        schemas.py
      auth/
        router.py
        service.py
        schemas.py
      shared/
        exceptions.py
        pagination.py
        security.py
        types.py
    models/
      user.py
      route.py
      stop.py
      alert.py
      report.py
      active_trip.py
    seed/
      routes.json
      stops.json
      alerts.json
      trips.json
  migrations/
  tests/
  Dockerfile
  requirements.txt
  requirements-dev.txt
docker-compose.yml
```

## 8. v1 Modules

### 8.1 Planner

Responsibilities:

- search trip options between origin and destination
- return detailed itinerary for a trip
- start an active trip session
- advance an active trip session

v1 implementation model:

- rule-based search over seeded route/stop data
- no full transit optimization engine yet
- no real-time rerouting engine yet

### 8.2 Stops

Responsibilities:

- list known stops
- return stop detail
- expose stop metadata needed by the frontend

### 8.3 Arrivals

Responsibilities:

- return home arrivals feed
- return arrivals for a specific stop
- expose ETA, occupancy, and status values in the frontend contract shape

v1 note:

- arrivals may be generated from seeded schedules plus simple heuristics before real feed integration exists

### 8.4 Alerts

Responsibilities:

- return active alerts
- filter alerts by affected routes

### 8.5 Reports

Responsibilities:

- create user-submitted incident reports
- support anonymous and authenticated reports
- store enough metadata for later moderation and analytics

This module matters in v1 because crowdsourcing is a core product differentiator.

### 8.6 Users

Responsibilities:

- register users
- authenticate users
- return current user profile
- expose basic crowdsourcing-related metadata

v1 user value should focus on:

- report attribution
- reputation scaffolding
- future trust/moderation hooks

Users do not require a full social or personalization platform in v1.

## 9. Canonical API Surface

All backend routes are exposed under `/api`.

### 9.1 Planner

`GET /api/planner/search`

Query params:

- `from`: string
- `to`: string
- `sort`: `fastest | cheapest | fewest`

Response:

- `200 OK` with `TripOption[]`

This must match `PlannerProvider.searchTrips()` in the frontend contract.

`GET /api/planner/trips/{tripId}`

Response:

- `200 OK` with `TripDetailDto`
- `404 Not Found` if the trip does not exist

`POST /api/planner/trips/{tripId}/start`

Auth:

- optional in the first implementation, but should support associating the trip to a user when authenticated

Response:

- `200 OK` with `ActiveTripDto`
- `404 Not Found`

`POST /api/planner/trips/{tripId}/advance`

Body:

```json
{
  "currentStepIndex": 1
}
```

Response:

- `200 OK` with updated `ActiveTripDto`
- `404 Not Found`

Reason for including `advance`:

The current frontend contract already includes `advanceStep`, and active trip state is backend-owned in v1.

### 9.2 Stops

`GET /api/stops`

Response:

- `200 OK` with `Stop[]`

Optional later query params:

- `lat`
- `lng`
- `radius`

These can be added later without breaking the current frontend.

`GET /api/stops/{stopId}`

Response:

- `200 OK` with `StopDetailDto`
- `404 Not Found`

### 9.3 Arrivals

`GET /api/arrivals/home`

Response:

- `200 OK` with `Arrival[]`

`GET /api/arrivals/stops/{stopId}`

Response:

- `200 OK` with `Arrival[]`
- `404 Not Found` if the stop does not exist

### 9.4 Alerts

`GET /api/alerts`

Optional query:

- `routeIds=100,302,T1`

Response:

- `200 OK` with `Alert[]`

The backend may support route filtering on the same endpoint rather than requiring a dedicated route-specific endpoint.

### 9.5 Reports

`POST /api/reports`

Body:

```json
{
  "type": "delay",
  "routeId": "100",
  "stopId": "s1",
  "description": "Bus is running late"
}
```

Response:

- `201 Created`

The backend should also derive metadata where possible:

- authenticated `userId` if present
- request timestamp
- source IP or fingerprint if policy allows

### 9.6 Users and Auth

`POST /api/auth/register`

`POST /api/auth/login`

`GET /api/users/me`

These endpoints should be minimal in v1 and exist mainly to support the report/crowdsourcing model.

## 10. Contract Alignment Rules

The frontend contract files are the canonical source for response shapes during v1:

- `TransitPulseWebsite/src/data/contracts/planner.ts`
- `TransitPulseWebsite/src/data/contracts/stops.ts`
- `TransitPulseWebsite/src/data/contracts/alerts.ts`
- `TransitPulseWebsite/src/data/contracts/arrivals.ts`

Rule:

- backend responses must align with these shapes closely enough that frontend API providers need little or no adapter logic

Important implementation rule:

- invalid IDs must return `404`
- the backend must never silently substitute a different entity

## 11. Data Model

### 11.1 Core tables for v1

Required tables:

- `users`
- `routes`
- `stops`
- `route_stops`
- `alerts`
- `reports`
- `trip_templates` or equivalent persisted planner candidates
- `active_trips`
- `active_trip_steps`

Optional but useful:

- `user_reputation_events`
- `report_votes` or `report_confirmations`

### 11.2 Minimal table intent

`users`

- id
- email
- password_hash
- display_name
- created_at
- reputation_score
- is_active

`routes`

- id
- short_name
- long_name
- mode
- fare_min
- fare_max
- color

`stops`

- id
- name
- address
- lat
- lng
- live

`route_stops`

- route_id
- stop_id
- stop_order

`alerts`

- id
- severity
- title_es
- title_en
- body_es
- body_en
- emitted_at
- is_active

`reports`

- id
- user_id nullable
- route_id nullable
- stop_id nullable
- type
- description
- status
- created_at

`active_trips`

- id
- trip_id
- user_id nullable
- current_step_index
- started_at
- status

`active_trip_steps`

- id
- active_trip_id
- step_index
- kind
- route nullable
- time_label
- minutes
- payload_json

## 12. Seed Data Strategy

v1 starts with backend-owned seed data.

This means:

- planner search can work without external feeds
- stops and routes exist immediately
- alerts can be preloaded
- arrivals can be generated from deterministic seed/schedule logic

Seed data should be version-controlled.

External integrations are added later behind adapter boundaries, not by changing API contracts.

## 13. External Integrations

External providers are deferred behind service adapters.

Likely future integrations:

- map/geocoding APIs
- transport feed APIs
- weather APIs

Rules:

- external calls happen only on the backend
- frontend never sees provider credentials
- failures from external APIs must degrade gracefully into partial responses or known error states

## 14. Performance and Cost Constraints

v1 targets:

- normal read responses under 5 seconds
- common seeded-data reads well under 1 second

Cost strategy:

- no Redis
- no queue
- no always-on application server in production
- Lambda-compatible backend package

The architecture should stay cheap by default, even if some endpoints are less optimized than a long-running cached service.

## 15. Security Requirements

Minimum v1 requirements:

- HTTPS in production
- request validation at the API boundary
- hashed passwords
- JWT verification for authenticated endpoints
- environment-managed secrets
- backend-only access to external API credentials
- basic rate limiting logic, implemented without Redis if necessary

If rate limiting is not implemented immediately, it should be documented as a known gap rather than hidden.

## 16. Local Development

Local development must be easy and cheap.

Required local stack:

- backend app container
- postgres container

Optional local additions:

- pgAdmin
- migration runner

Expected developer workflow:

1. `docker compose up`
2. run migrations
3. load seed data
4. run frontend against local backend

## 17. Testing Requirements

The backend must include:

- unit tests for core services
- API tests for route behavior
- contract tests for frontend-facing response shapes

Minimum API tests required in v1:

- planner search returns valid `TripOption[]`
- invalid `tripId` returns `404`
- invalid `stopId` returns `404`
- alerts filtering works
- report creation succeeds
- authenticated user lookup works

## 18. Migration Path After v1

Likely future additions after the initial backend is stable:

- real external transit feeds
- real prediction module
- geospatial nearby-stop queries
- richer user trust/reputation model
- favorites and profile enrichment
- alert subscriptions
- caching if traffic justifies it

## 19. Definition of Done

The backend v1 is done when:

- all canonical `/api` routes in this document exist
- PostgreSQL is the only required datastore
- the frontend can switch from mock providers to API providers without UI rewrites
- invalid IDs return explicit `404`
- active trip state is backend-owned
- report submission works
- user registration/login/me works
- local Docker setup supports end-to-end testing

## 20. Final Authority

If older docs conflict with this file:

- this file wins for backend implementation
- frontend contract files win for response shape details
- older architecture or requirements docs are interpreted as context, not as canonical API design
