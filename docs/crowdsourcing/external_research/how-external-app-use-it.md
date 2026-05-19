Here’s what’s publicly knowable. Waze does not publish the exact internal ranking/decay algorithm, but its partner feed docs and transportation-agency guidance reveal the useful model: every report has freshness, crowd feedback, and reporter reputation signals.

For Waze-style event reports, the public feed exposes two key scores. “Reliability” is 0–10 and is based on user reactions plus the reporter’s level; Waze levels run from 1 to 6, with higher levels representing more experienced/trusted contributors. “Confidence” is based on other users reacting “Thumbs up” or “Not there”; Waze’s current docs describe this as ranging from -1 to 5 in one section, though the same page’s data table also says 0–10, so consumers should treat the exact scale carefully and normalize it internally. ([Google Help][1])

Transportation agencies that consume Waze data often combine confidence and reliability to decide whether an event is worth acting on. FHWA notes that many agencies filter out low-reliability Waze events, and that short-duration or low-confidence/low-reliability reports are more likely to be false positives. FHWA also flags two practical problems: duplicate crowd reports and reports that remain active too long after the real-world event clears. ([FHWA Operations][2])

For decay/freshness, transit systems give a clearer public benchmark than Waze. GTFS Realtime best practices say feeds should refresh at least every 30 seconds or whenever vehicle info changes; Trip Updates and Vehicle Positions should not be older than 90 seconds, while Service Alerts should not be older than 10 minutes. ([General Transit Feed Specification][3]) Google’s transit ingestion docs are more tolerant but still discard stale data: VehiclePosition messages are considered stale after 15 minutes, Trip Updates after 1 hour, and alerts can remain until removed, though Google recommends alert feeds update at least every 10 minutes. ([Google Help][4]) Transit app is stricter for rider-facing vehicle dots: it requests vehicle positions frequently and discards vehicle positions older than 3 minutes. ([resources.transitapp.com][5])

For a bus-route project, I’d model reports as three scores rather than one magic number:

`freshness_score`: starts at 1.0 and decays by report type. For live bus location or “bus passed stop,” use a half-life around 60–120 seconds and hard-expire after 3–5 minutes. For “bus is crowded,” half-life around 5–10 minutes. For “stop closed,” “detour,” “broken shelter,” or “unsafe stop condition,” use a much longer TTL, but require rechecks or moderator/agency confirmation.

`confirmation_score`: increase when independent riders near the same stop/route/time confirm the report. Decrease when riders say “not there,” when GPS evidence contradicts it, or when the bus/route state makes it impossible. Weight confirmations more if the user is physically near the route, moving with the bus, or has recently boarded using your app.

`reporter_trust_score`: start neutral, then adjust based on historical agreement with later evidence. Reward reports that were confirmed by other riders, matched GTFS-RT/vehicle GPS later, or were accepted by an operator. Penalize reports repeatedly contradicted by nearby users or telemetry. Keep penalties soft at first so new users are not useless.

A practical formula could be:

`event_score = 0.45 * freshness + 0.35 * confirmation + 0.20 * reporter_trust`

Then apply thresholds by action:

For “show quietly in UI,” use a low threshold, like 0.35.

For “show as likely true,” use around 0.55.

For “send push alert / change ETA / reroute user,” use around 0.75, or require one trusted reporter plus one independent confirmation.

For “agency/operator dashboard incident,” use around 0.65 but mark it as “crowd-reported” until confirmed.

For bus routes, the best confirmation signals are not just thumbs-up/down. Use location and motion: “this user is on route 5, moving along the route at bus-like speed, near trip_id X.” A report from someone actually riding the bus should count more than a report from someone several blocks away. Also deduplicate aggressively by route, direction, stop/segment, report type, and time window, because FHWA specifically calls duplicate Waze reports a known issue. ([FHWA Operations][2])

Suggested starting TTLs:

| Report type                          |                            Half-life |              Hard expiry |       Confirmations needed |
| ------------------------------------ | -----------------------------------: | -----------------------: | -------------------------: |
| Bus location / “bus just passed”     |                            60–90 sec |                  3–5 min |       1 rider or GPS match |
| Arrival delay                        |                              2–3 min |                10–15 min |      GPS/GTFS-RT preferred |
| Crowding                             |                                5 min |                15–25 min | 2 riders or onboard signal |
| Driver skipped stop                  |                             5–10 min |              End of trip |    2 riders or GPS pass-by |
| Stop obstruction / stop closed       |                               1–6 hr | 24 hr+ with revalidation |          2 riders or staff |
| Detour / road blockage affecting bus |                            10–30 min |  1–3 hr unless confirmed |       2 riders or operator |
| Safety/service issue                 | No public auto-display until checked |           workflow-based |         moderator/operator |

For implementation, store every report as an immutable observation, then maintain a derived “active event” object. The active event merges nearby similar reports, tracks positive/negative confirmations, applies time decay, and exposes a normalized confidence score to the UI/API. That keeps your raw data auditable while letting the user-facing layer stay simple.

The big takeaway: Waze-style systems do not depend on one confirmation threshold. They combine age, nearby user reactions, reporter history, and event type. For buses, add GTFS/GTFS-RT alignment and rider-on-vehicle detection, because those give you much stronger trust signals than generic map reports.

[1]: https://support.google.com/waze/partners/answer/13458165?hl=en "Waze Data Feed specifications - Waze Partners Help"
[2]: https://ops.fhwa.dot.gov/publications/fhwahop18084/ch2.htm "Considerations of Current and Emerging Transportation Management Center Data - Chapter 2. Emerging Data Sources - FHWA Office of Operations"
[3]: https://gtfs.org/documentation/realtime/realtime-best-practices/ "Best Practices - General Transit Feed Specification"
[4]: https://support.google.com/transitpartners/answer/10104663?hl=en "How data gaps affect realtime feeds - Transit Partners Help"
[5]: https://resources.transitapp.com/article/463-vehicle-positions "Vehicle Positions - Transit Partners"
