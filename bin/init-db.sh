#!/usr/bin/env bash
# Bootstrap a freshly-deployed Postgres with schema + seed data.
# Idempotent: safe to re-run. Used on first Fly deploy via:
#   fly ssh console -C "/var/task/bin/init-db.sh"
# For local docker-compose use:
#   docker compose exec backend bin/init-db.sh
set -euo pipefail

cd "$(dirname "$0")/.."
exec python -m app.seed.load
