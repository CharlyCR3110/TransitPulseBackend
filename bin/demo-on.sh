#!/usr/bin/env bash
# Bring the deployed TransitPulse stack back online after demo-off.sh.
# Idempotent: safe to re-run if already on.
#
# What this does:
#   - Scales the Fly app to 1 machine → backend boots back up.
#   - Polls the public healthcheck until it responds (or 90s timeout).
#   - Prints both URLs when ready.
set -euo pipefail

APP="${TRANSITPULSE_APP:-transitpulse-backend}"
BACKEND_URL="${TRANSITPULSE_BACKEND_URL:-https://transitpulse-backend.fly.dev}"
FRONTEND_URL="${TRANSITPULSE_FRONTEND_URL:-https://transitpulse-website.vercel.app}"
HEALTH_URL="$BACKEND_URL/api/v1/health"

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

echo "→ Resuming Fly app: $APP"
"$FLY" scale count 1 --app "$APP" --yes

echo
echo "→ Waiting for backend healthcheck (up to 90s)..."
for i in $(seq 1 45); do
  if curl -sSf -o /dev/null --max-time 3 "$HEALTH_URL"; then
    echo "✓ Backend healthy:  $BACKEND_URL/api/v1"
    echo "✓ Frontend live:    $FRONTEND_URL"
    echo
    echo "Demo ready in your browser: $FRONTEND_URL"
    exit 0
  fi
  printf "."
  sleep 2
done

echo
echo "⚠ Backend did not respond within 90s." >&2
echo "  Check logs: $FLY logs --app $APP" >&2
echo "  Status:     $FLY status --app $APP" >&2
exit 1
