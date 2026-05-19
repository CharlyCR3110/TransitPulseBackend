# Crowdsourcing Feature — Project Summary

## Artifacts

| File | Description |
|------|-------------|
| `rough-idea.md` | Initial concept and existing foundation |
| `idea-honing.md` | 11 Q&A rounds refining scope and decisions |
| `research/codebase-analysis.md` | Deep analysis of existing models, services, and integration points |
| `external_research/how-external-app-use-it.md` | Reference: Waze, GTFS-RT, Transit App patterns |
| `design/detailed-design.md` | Full spec: endpoints, data models, flows, config, error handling, testing |
| `implementation/plan.md` | 13-step incremental plan with checklist |

## Key Design Decisions

1. **Active trip only** — reports require trip context; route+direction auto-inferred
2. **Route-scoped** — reports tied to a route+direction, not segments or pins
3. **Hybrid TTL** — auto-expire by type, confirmations extend, manual resolve available
4. **Confirm + detail** — richer than upvote/downvote; feeds into predictions later
5. **Minimal spam prevention** — rate limiting + dedup for MVP; reputation-weighted later
6. **Phased predictions** — soft signal badges first, direct ETA integration later
7. **Context-aware visibility** — only show reports for routes the user is currently viewing

## Implementation Overview

- **Steps 1-3:** Foundation (DB schema, config, direction inference)
- **Steps 4-7:** Backend API (submit, list, confirm, deny)
- **Step 8:** Arrivals integration (crowdReports on arrival cards)
- **Step 9:** Backend deploy (Neon migration + Fly deploy + smoke test)
- **Steps 10-12:** Frontend (report form, badges, confirm/deny UI)
- **Step 13:** Frontend deploy (Vercel deploy + end-to-end smoke test)

## Next Steps

1. Review the design doc at `design/detailed-design.md`
2. Start implementation following the checklist in `implementation/plan.md`
3. Each step is designed to be demoable — verify each before moving to the next
