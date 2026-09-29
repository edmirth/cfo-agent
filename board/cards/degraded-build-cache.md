---
title: Don't cache a build whose Tripletex reports failed
owner: @agent
milestone: #reliability
created: 2026-09-29
---
## Goal
`freshness.Cached` stores whatever `build()` returns, including a build whose reports failed. Observed this session: Tripletex's MCP returned HTTP 500 four times, `Resultatrapport feilet: fetch_report svarte 500`, and `/api/overview` came back with every KPI `null` — then served that from cache for the full 600 seconds. It only recovered on restart.

The front page goes blank for ten minutes because of a transient upstream blip. The behaviour predates the single-flight change; the old check-then-store cached a degraded build too.

**Note.** Found by verification, not from TODO.md. This is the fifth fix flagged after the other four were applied.

## Done when
- [ ] A build whose reports failed is not cached, or is cached with a short retry TTL
- [ ] The degraded state is distinguishable from a genuine zero — a company really can have no receivables
- [ ] The panel says the figures could not be fetched rather than showing null
- [ ] A test forces a failed report and asserts the next call retries

## Log
- 2026-09-29 (agent): created
