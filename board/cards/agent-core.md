---
title: Extract the shared agent core so every AI job runs on it
owner: @agent
milestone: #agent
created: 2026-10-04
---
## Goal
`agent.py` holds two things at once: the CFO agent's machinery (Claude client, read-only toolset, tool loop, local tools, `verify`, rollback, prompt cache) and the chat job. `summary.py` and `industry.py` call Claude their own way, without `verify` or the read-only toolset.

Every MVP job the playbook asks for (the morning watch, the Monday brief, the health check) needs the same machinery. Build it once: `agent/core.py` runs a job given its prompt, the tools it may use and the output it should produce; `agent/tools.py` holds the local tools; chat becomes `agent/jobs/chat.py`. See the target architecture map.

## Done when
- [ ] One function runs any agent job from its prompt, its allowed tools and its expected output
- [ ] Chat runs on it and behaves exactly as before: all tests pass and one chat turn is checked by hand
- [ ] `summary.py` and the industry classification call Claude through it, so `verify` applies to them too
- [ ] A job can only call the local tools it was given
- [ ] Tokens, cost and the number of unverified figures are logged for every job run

## Log
- 2026-10-04 (agent): created from the AI CFO Strategy Playbook gap analysis
