#!/usr/bin/env bash
# Pause the deployed TransitPulse stack so it stops accruing Fly billing.
# Idempotent: safe to re-run.
#
# What this does:
#   - Scales the Fly app to 0 machines → backend stops, billing pauses.
#   - Leaves Vercel + Neon alone (both free tier; Neon auto-suspends compute).
#   - Preserves all secrets, config, code, and the database.
#
# To bring everything back: ./demo-on.sh
set -euo pipefail

APP="${TRANSITPULSE_APP:-transitpulse-backend}"

# Find flyctl: prefer $FLYCTL env, then PATH, then default install location.
if [ -n "${FLYCTL:-}" ]; then
  FLY="$FLYCTL"
elif command -v flyctl >/dev/null 2>&1; then
  FLY="$(command -v flyctl)"
elif [ -x "$HOME/.fly/bin/flyctl" ]; then
  FLY="$HOME/.fly/bin/flyctl"
else
  echo "✗ flyctl not found. Install: curl -L https://fly.io/install.sh | sh" >&2
  exit 1
fi

echo "→ Pausing Fly app: $APP"
"$FLY" scale count 0 --app "$APP" --yes

echo
"$FLY" status --app "$APP" || true

echo
echo "✓ Fly machine stopped — billing paused (~\$0/day)."
echo "  Vercel: still live at https://transitpulse-website.vercel.app (free tier)"
echo "  Neon:   compute auto-suspended on idle (free tier)"
echo "  DB data, secrets, and code are preserved."
echo
echo "To resume: $(dirname "$0")/demo-on.sh"
