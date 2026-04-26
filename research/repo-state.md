# Research — Repository State

A short grounding pass to confirm what exists at `/home/charlygg/workspace/` before the implementation plan starts.

## Workspace contents (as of 2026-04-25)

```
/home/charlygg/workspace/
├── backend-final-spec.md        — the canonical spec (source for rough-idea.md)
├── TransitPulseBackend/         — this PDD project directory
└── TransitPulseWebsite/         — the existing Next.js frontend
```

Notable absences:

- **No `backend/` directory exists yet.** The implementation plan starts greenfield in a new top-level `backend/`, exactly as spec §7 dictates.
- **No `docker-compose.yml` at the workspace root.** The compose file is greenfield as part of v1.
- **No `.git` at the workspace root.** No git repository exists at the workspace level. (`TransitPulseWebsite/.git` was not detected either — frontend is presumably tracked elsewhere or this is a fresh checkout.)
- **No `docs/` directory at the workspace root**, despite the spec referencing `docs/01_requirements_documentation (1).docx` and `docs/02_arquitectura.docx`. Per the user, those `.docx` files are skipped (Q14 / research scope decision).

## Frontend snapshot (relevant bits only)

```
TransitPulseWebsite/
├── package.json                 — Next.js project
├── src/
│   ├── data/
│   │   ├── contracts/*.ts       — canonical wire shapes (read in detail)
│   │   ├── providers/mock/      — mock provider implementations
│   │   ├── transit.ts           — I18N table + mock data fixtures
│   │   ├── alerts.ts | arrivals.ts | routes.ts | stops.ts | trips.ts
│   └── types/transit.ts         — type definitions referenced by contracts
├── node_modules/
└── …other Next.js files
```

The frontend is established but the API providers themselves do not exist yet — only the mock providers under `src/data/providers/mock/`. A sibling `src/data/providers/api/` is the expected target for the real-API providers; it is **not in backend scope**, but the design doc should call it out as a coordinated frontend task that depends on the backend being live.

## Implications for the implementation plan

- Step 1 of implementation = create the `backend/` directory with the layout from spec §7.
- Step 2 onwards builds inside that directory; nothing reaches into `TransitPulseWebsite/` from the backend.
- A `docker-compose.yml` lives at the workspace root (`/home/charlygg/workspace/docker-compose.yml`) and orchestrates `backend/` + Postgres.
- No git initialization is part of this plan; if the user wants a repo, that's a separate ask.
- The frontend `I18N` table is a **read-only contract dependency** for backend tests — tests should snapshot the keys they expect, not import live frontend code.
