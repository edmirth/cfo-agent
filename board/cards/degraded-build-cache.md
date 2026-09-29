---
title: Retry failed Tripletex report builds instead of caching empty KPIs
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
- 2026-09-30 (agent): **diagnosed the 500s, and the cause is ours, not theirs.**
  Across 1 173 logged MCP calls this session, 99 returned HTTP 500. They are not
  random and not one bad report — the failure rate tracks how many requests are
  in flight in the same second:

  | concurrent calls | calls | 500s | failure rate |
  |---|---|---|---|
  | 1-4 | 340 | 1 | 0.3 % |
  | 5-8 | 274 | 4 | 1.5 % |
  | 9-15 | 365 | 26 | 7.1 % |
  | 16+ | 240 | 76 | 31.7 % |

  Every report is affected, and so are non-report tools
  (`get_voucher_inbox_count`, `search_employees`,
  `get_supplier_invoices_for_approval`). Fetching the worst offender
  (`Resultatrapport`) once, on its own, succeeds every time.

  `mcp_client.py` has no semaphore, no retry and no connection limit — just
  `httpx.AsyncClient(timeout=120)`. Eight modules each call `asyncio.gather`,
  and they nest: `industry` gathers `overview`, which itself gathers four
  reports. A cold front page puts 16+ report requests in flight at once.

  So this card is bigger than caching. The fix is three things:
  1. A semaphore in `mcp_client` capping in-flight requests (4 looks safe —
     0.3 % at that level).
  2. Retry on 5xx with backoff, since an isolated retry succeeds.
  3. Only then the original point: do not cache a build that came back degraded.

  Worth knowing: Tripletex answers overload with a 500 and an HTML error page,
  not a 429 with `Retry-After`. That is an unhandled overload rather than
  deliberate throttling, and their MCP exposes `submit_feedback` for reporting
  it.
