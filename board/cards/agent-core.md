---
title: Extract the shared agent core so every AI job runs on it
owner: @agent
milestone: #agent
created: 2026-10-04
priority: 3
---
## Goal
`agent.py` holds two things at once: the CFO agent's machinery (Claude client, read-only toolset, tool loop, local tools, `verify`, rollback, prompt cache) and the chat job. `summary.py` and `industry.py` call Claude their own way, without `verify` or the read-only toolset.

Every MVP job the playbook asks for (the morning watch, the Monday brief, the health check) needs the same machinery. Build it once: `agent/core.py` runs a job given its prompt, the tools it may use and the output it should produce; `agent/tools.py` holds the local tools; chat becomes `agent/jobs/chat.py`. See the target architecture map.

## Done when
- [x] One function runs any agent job from its prompt, its allowed tools and its expected output
- [x] Chat runs on it and behaves exactly as before: all tests pass and one chat turn is checked by hand
- [x] `summary.py` and the industry classification call Claude through it, so `verify` applies to them too
- [x] A job can only call the local tools it was given
- [x] Tokens, cost and the number of unverified figures are logged for every job run

## Log
- 2026-10-04 (agent): created from the AI CFO Strategy Playbook gap analysis
- 2026-10-04 (agent): priority 3 in Next: every agent job (brief, watch, health check) runs on it.
- 2026-10-05 (agent): built. `backend/agent/` replaces `agent.py`:
  `core.py` runs any `Job(name, system, tools, tripletex, output)` — `stream`
  for the chat, `complete` for everything else (parses JSON, raises on a
  cut-off or failed answer). `tools.py` holds the local tools; a job is
  offered only the ones it names and a call to any other is answered "No such
  tool" without running. `jobs/chat.py` is the chat. `summary.py` and the
  industry classification are jobs on the core, so `verify` reads them too;
  the summary stores its unverified figures with the text.
- 2026-10-05 (agent): every run logs rounds, tokens in/out, cache read/write,
  cost in USD (first-party rates, `core.PRICES`; unpriced model → "ukjent
  pris") and the number of figures without a source. Usage is summed over all
  rounds; the `done` event still carries the last round's, as before.
- 2026-10-05 (agent): the core imports `cards`/`memory`/`trace` inside
  `tools.run`, because memory → definitions → industry → core would otherwise
  be a cycle. Checked one chat turn by hand on live data: same events as
  before, 6 of 6 figures traced, logged at 0.69 USD (first turn writes the
  102k-token system prompt to cache). 223 tests pass.

