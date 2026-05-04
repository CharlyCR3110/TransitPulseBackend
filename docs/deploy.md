# Deploy runbook — TransitPulse backend

Production target: `https://transitpulse-backend.fly.dev` (Fly.io app `transitpulse-backend`, region `dfw`).
Database: Neon project `TransitPulse` (`curly-forest-37548893`), region `aws-us-east-1`.

This runbook is the canonical guide for first-time provisioning, redeploys, and rotation. Last verified: 2026-05-03.

---

## Prerequisites

- Fly CLI: `curl -L https://fly.io/install.sh | sh` (installs to `~/.fly/bin/flyctl`).
- Logged in: `flyctl auth login` (org defaults to your personal — confirm with `flyctl orgs list`).
- Neon account at https://neon.tech (free tier).
- Working directory: `TransitPulseBackend/`.

---

## First-time provisioning

### 1. Create the Neon project

Use the Neon dashboard or `neonctl projects create --name TransitPulse --region-id aws-us-east-1`.
After creation, copy the **pooled** connection string (host contains `-pooler`).

Convert the scheme for SQLAlchemy: replace `postgresql://` with `postgresql+psycopg://`.
Strip `channel_binding=require` if present — `sslmode=require` is sufficient.

Example:
```
postgresql+psycopg://USER:PWD@ep-xxx-pooler.region.aws.neon.tech/neondb?sslmode=require
```

### 2. Create the Fly app

From `TransitPulseBackend/`:

```sh
flyctl launch \
  --name transitpulse-backend \
  --org personal \
  --regions dfw \
  --no-deploy --no-db --no-redis --no-object-storage --no-github-workflow \
  --ha=false \
  --vm-cpu-kind shared --vm-cpus 1 --vm-memory 512 \
  --internal-port 8080 \
  --dockerfile Dockerfile \
  --yes
```

This creates the Fly app and writes `fly.toml`. Region note: `mia` is deprecated as of 2026-05; `dfw` is the current closest reliable US region. Other reasonable options: `gdl` (Guadalajara), `bog` (Bogotá).

### 3. Tune `fly.toml`

The committed `fly.toml` already contains the following critical settings — verify after a fresh `flyctl launch` overwrites it:

- `primary_region = 'dfw'`
- `[http_service] auto_stop_machines = 'off'` and `min_machines_running = 1` (no scale-to-zero — avoids cold-start UX hits during demos).
- `[[http_service.checks]]` GET `/api/v1/health` every 15s with a 10s grace period.

### 4. Set secrets

```sh
JWT=$(openssl rand -base64 48 | tr -d '\n')

flyctl secrets set \
  "DATABASE_URL=postgresql+psycopg://USER:PWD@ep-xxx-pooler.region.aws.neon.tech/neondb?sslmode=require" \
  "JWT_SECRET=$JWT" \
  "CORS_ORIGINS=http://localhost:3000" \
  "SENTRY_ENVIRONMENT=staging" \
  "LOG_LEVEL=INFO" \
  --stage
```

Optional — only if a Sentry project exists:
```sh
flyctl secrets set "SENTRY_DSN=https://...@sentry.io/..." --stage
```

`--stage` queues the secrets without restarting; the next `flyctl deploy` applies them.

### 5. Deploy

```sh
flyctl deploy --remote-only --ha=false
```

`--remote-only` builds on Fly's remote builder — no local Docker daemon needed.

### 6. Bootstrap schema + seed data

The app does NOT auto-create tables on startup; you must run the seed script once:

```sh
flyctl ssh console -C "/var/task/bin/init-db.sh"
```

`init-db.sh` runs `python -m app.seed.load`, which:
1. `Base.metadata.create_all(bind=engine)` — creates all SQLAlchemy tables.
2. Inserts the seed alerts, stops, and trip templates.

Idempotent — safe to re-run.

> Known UX wart: the `flyctl ssh console -C` command sometimes appears to hang at "Connecting to..." before printing the script output. The script does run; verify by hitting `/api/v1/alerts` after ~30s.

### 7. Verify

```sh
BASE=https://transitpulse-backend.fly.dev/api/v1
curl -sS $BASE/health                                # {"status":"ok"}
curl -sS $BASE/alerts | head -c 200                  # 4 alerts
curl -sS $BASE/stops | python3 -c "import sys,json; d=json.load(sys.stdin); print(len(d), d[0]['lat'], d[0]['lng'])"
                                                     # 3, 9.9343, -84.0508

# Auth round-trip
curl -sS -X POST $BASE/auth/register \
  -H 'content-type: application/json' \
  -d '{"email":"smoke@example.com","password":"smoke12345!","displayName":"Smoke"}'
TOK=$(curl -sS -X POST $BASE/auth/login \
  -H 'content-type: application/json' \
  -d '{"email":"smoke@example.com","password":"smoke12345!"}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['accessToken'])")
curl -sS -H "authorization: Bearer $TOK" $BASE/users/me/stats   # {"trips":0}
```

---

## Redeploys

Code-only changes:
```sh
flyctl deploy --remote-only --ha=false
```

Secret-only changes:
```sh
flyctl secrets set KEY=value             # restarts the machine immediately
flyctl secrets set KEY=value --stage     # waits for next deploy
```

Add the Vercel preview/prod URL to CORS once Step 10 lands:
```sh
flyctl secrets set "CORS_ORIGINS=https://YOUR-VERCEL-URL,http://localhost:3000"
```

---

## Rolling a new staging environment

If you ever need a parallel staging app (e.g., for previewing a destructive migration):

1. `flyctl apps create transitpulse-backend-staging`
2. Branch the Neon project: `neonctl branches create --project-id curly-forest-37548893 --name staging`
3. Set `DATABASE_URL` on the new app to the branch's connection string.
4. `flyctl deploy --app transitpulse-backend-staging --remote-only --ha=false`
5. Seed: `flyctl ssh console --app transitpulse-backend-staging -C "/var/task/bin/init-db.sh"`

---

## Operations

### Logs

```sh
flyctl logs                       # tail
flyctl logs --app transitpulse-backend
```

### Status

```sh
flyctl status
flyctl machine list
```

### SSH

```sh
flyctl ssh console
```

### Rotating secrets

JWT (forces all users to re-login):
```sh
flyctl secrets set "JWT_SECRET=$(openssl rand -base64 48 | tr -d '\n')"
```

Neon password — rotate in the Neon dashboard, then update the Fly secret with the new pooled DSN.

### Rolling back

Fly keeps a release history:
```sh
flyctl releases
flyctl releases rollback v<N>
```

---

## Cost expectations

- Fly: 1 × `shared-cpu-1x` 512MB pinned in `dfw` ≈ $3.89/mo. The `mia` 256MB plan from the original spec ($1.94/mo) is unavailable due to region deprecation; 512MB is also safer for FastAPI's idle footprint.
- Neon: free tier (≤ 0.5 GB storage, 100h compute/mo). Pooled endpoint scales to zero after `suspend_timeout_seconds`.
- Total demoable cost: ~$4/mo until traffic exceeds Neon's free tier.

---

## Known limitations (post-MLP followups)

- No alembic migrations yet — schema is bootstrapped by `Base.metadata.create_all`. Schema changes require a manual SQL apply or a destructive recreate. Tracked in `.sop/planning/transitpulse-mlp/followups.md` (item 1).
- No CI/CD — every deploy is a manual `flyctl deploy`.
- Single region (`dfw`). Acceptable for MLP demo.
