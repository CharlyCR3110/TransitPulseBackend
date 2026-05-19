# Crowdsourcing Feature — Rough Idea

A Waze-like crowdsourcing feature for TransitPulse where bus riders can report real-time conditions (delays, overcrowding, breakdowns, accidents, route changes, safety issues) so other users on the same route get notified. Reports should influence predictions and help riders make better decisions.

## Key Differentiator

This is what sets TransitPulse apart from other transit apps: real-time, community-driven information that fills the gap left by transit agencies that don't provide live tracking or incident data.

## Existing Foundation

- `Report` model already exists with type enum: DELAY, BREAKDOWN, ACCIDENT, OVERCROWDING, ROUTE_CHANGE, SAFETY, OTHER
- Report status workflow: NEW → CONFIRMED → DISMISSED → RESOLVED
- `POST /api/v1/reports` endpoint exists (submit only, no listing/querying)
- User model has a `reputation_score` field (unused)
- Active trip tracking links users to their current journey
- Predictions service uses static `DelayPrior` data (historical, not real-time)
- WebSocket dependency installed but not wired up
- Alert model with route associations exists
