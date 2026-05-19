# Crowdsourcing Feature — Requirements Clarification

## Q1: Should anonymous users be able to submit reports, or only authenticated users?

Currently the `POST /reports` endpoint accepts both (user is optional). Allowing anonymous reports lowers the barrier but opens the door to spam/abuse. Requiring auth gives us reputation tracking and accountability. A middle ground could be: anonymous can report, but their reports carry less weight and need more confirmations to be promoted.

**Answer:** Middle ground — anyone can submit reports, but anonymous reports carry less weight and require more confirmations to be promoted. Authenticated users' reports are weighted by their reputation score.

---

## Q2: How should other users confirm or interact with reports?

When a user sees a report (e.g., "400p is delayed at Hospital"), how should they engage with it? Options include:
- **Simple upvote/downvote** — binary agree/disagree, lightweight
- **Confirm/Deny buttons** — "I see this too" / "Looks normal to me", semantically clearer than votes
- **Confirm + add detail** — users can confirm and optionally add context (e.g., "15 min delay" or "bus broke down")

**Answer:** Confirm + add detail — users can confirm a report and optionally add extra context. Deny is also available. This gives us richer signal for predictions and helps other riders understand the severity.

---

## Q3: How should reports expire or resolve?

Reports about transit conditions are inherently short-lived — a delay right now may be gone in 30 minutes. How should reports age out?
- **Time-based auto-expiry** — reports automatically expire after a fixed window (e.g., 30 min, 1 hour, 2 hours depending on type)
- **Activity-based** — reports stay active as long as they keep getting confirmations; expire when confirmations stop
- **Manual resolution** — reports stay until the original reporter or a moderator marks them resolved
- **Hybrid** — auto-expire by default, but confirmations extend the lifetime; moderators can also resolve manually

**Answer:** Hybrid — each report type gets a default TTL (e.g., DELAY=30min, ACCIDENT=2h). Each confirmation extends the expiry. Moderators or the original reporter can resolve manually at any time.

---

## Q4: Should reports be tied to a specific stop, a route segment, or a general location?

This affects how we show reports to relevant users. Options:
- **Stop-scoped** — report is tied to a specific stop (e.g., "delay at Hospital stop"). Simple, but misses between-stop events like accidents.
- **Route-scoped** — report applies to an entire route (e.g., "400p is delayed"). Broad, but easy to notify all riders on that route.
- **Segment-scoped** — report covers a range of stops on a route (e.g., "400p delayed between Hospital and Heredia Centro"). Most precise but more complex UI.
- **Flexible** — reporter picks: stop, route, or drops a pin on the map for location-based events. System infers affected routes/stops.

**Answer:** Route-scoped — reports are tied to a route (and direction). This keeps the UI simple and ensures all riders on that route see the report. The existing Report model already has a `route_id` field, so this aligns well. A stop can optionally be attached for extra context but isn't required.

---

## Q5: How should riders be notified about reports on their route?

When a new report (or a report reaching "confirmed" status) affects a route the user cares about, how do they find out?
- **Passive (pull)** — reports show up when the user opens the app or checks arrivals. No push. Simplest to build.
- **In-app alerts** — a banner or toast appears if the user has the app open and is viewing an affected route or has an active trip on it.
- **Push notifications** — system sends a push notification to users with an active trip on the affected route, even if the app is in the background.
- **Layered** — start with in-app alerts (MVP), add push notifications later for users on active trips.

**Answer:** Layered, with context-aware filtering. MVP: in-app alerts only shown when the user is actively viewing the affected route (arrivals page, trip detail, etc.) — no irrelevant noise from routes the user isn't using. Later: push notifications for users with an active trip on that specific route. The key principle is relevance — only show reports for routes the user is currently interacting with.

---

## Q6: Should crowdsourced reports feed back into the predictions engine?

Right now `DelayPrior` uses historical data to estimate ETAs. Should confirmed crowd reports adjust predictions in real time?
- **No integration (MVP)** — reports are informational only; predictions stay purely historical. Simplest, no risk of bad data corrupting ETAs.
- **Soft signal** — confirmed DELAY reports add a visual warning badge on arrival times (e.g., "riders report delays") but don't change the predicted minutes.
- **Direct integration** — confirmed delay reports adjust the predicted ETA in real time (e.g., 3 confirmed delay reports on 400p → add estimated extra minutes to predictions).
- **Phased** — start with soft signal (badge/warning), graduate to direct integration once we have enough data and confidence in report quality.

**Answer:** Phased. Phase 1: soft signal — show a "riders report delays" badge alongside arrival predictions when confirmed DELAY reports exist for that route. Predictions stay untouched. Phase 2: once we trust report quality (reputation system working, enough volume), feed confirmed reports into ETA adjustments directly.

---

## Q7: How should we handle spam, abuse, and low-quality reports?

With anonymous reports allowed and community confirmations driving visibility, we need guardrails. What level of protection do you want at MVP?
- **Minimal** — rate limiting (e.g., max 5 reports/hour per IP or user) + basic dedup (same type+route within 10 min = merge). Rely on confirm/deny to surface quality.
- **Reputation-weighted** — same as minimal, plus: users who submit reports that get confirmed gain reputation; users whose reports get consistently denied lose reputation. Low-rep users' reports need more confirmations.
- **Moderation queue** — anonymous and low-rep reports go into a moderation queue; only high-rep or authenticated reports go live immediately.

**Answer:** Minimal for MVP — rate limiting + dedup. Let the confirm/deny mechanism naturally surface quality. Reputation-weighted filtering can be added later once there's enough user data to make it meaningful.

---

## Q8: What report types should be available at MVP?

The existing Report model has: DELAY, BREAKDOWN, ACCIDENT, OVERCROWDING, ROUTE_CHANGE, SAFETY, OTHER. Should we ship all of these at MVP, or start with a focused subset to keep the UI simple?
- **All existing types** — they're already in the model, just expose them all
- **Focused subset** — start with the most common/impactful ones (e.g., DELAY, OVERCROWDING, ACCIDENT) and add the rest later
- **Expanded** — add new types beyond what exists (e.g., BUS_NOT_RUNNING, DRIVER_ISSUE, DETOUR)

**Answer:** All existing types — DELAY, BREAKDOWN, ACCIDENT, OVERCROWDING, ROUTE_CHANGE, SAFETY, OTHER. They're already in the model, no reason to hold them back. Expansion can happen later if users request it.

---

## Q9: Should reporting be available only during an active trip, or anytime?

A user waiting at a stop or someone who just got off the bus might want to report too. Options:
- **Active trip only** — user must have started a trip to report. Guarantees context (route, direction, current position) but limits who can report.
- **Anytime** — user can report from any screen as long as they select a route. More reports, but less guaranteed context.
- **Anytime, but trip-aware** — reporting is always available, but if the user has an active trip, the route/direction are pre-filled and the report is linked to the trip for extra credibility.

**Answer:** Active trip only — users must have a started trip to submit a report. This guarantees we always have route, direction, and trip context. It also adds natural credibility since the user is provably on that route. Keeps the reporting surface focused.

---

## Q10: Do we need a direction field on reports?

The Heredia corridor has split directions (e.g., 400p Heredia→SJ vs 400p SJ→Heredia). A delay on one direction doesn't necessarily affect the other. Should reports capture direction?
- **Yes** — infer direction from the active trip's current step. Critical for showing relevant reports only to riders going the same way.
- **No** — apply the report to both directions of the route. Simpler, but noisier.

**Answer:** Yes — direction is inferred automatically from the user's active trip. Reports are only shown to riders heading the same direction. This aligns with how `route_stops` already tracks direction and keeps things relevant.

---

## Q11: How should reports appear in the frontend UI?

When a user is viewing arrivals or on an active trip and there are confirmed reports for their route+direction, how should we surface them?
- **Badge/icon on the route card** — a small icon (e.g., warning triangle, crowd icon) on the arrival or trip card. Tapping shows details.
- **Inline alert banner** — a colored banner at the top of the arrivals/trip view with a summary (e.g., "3 riders report delays on 400p → SJ").
- **Both** — badge on the card + expandable banner with details and option to confirm/deny.

**Answer:** Badge/icon on the route card — a small contextual icon (warning triangle for delays, crowd icon for overcrowding, etc.) on the arrival or trip card. Tapping the badge expands to show report details and the option to confirm/deny. Clean and non-intrusive.
