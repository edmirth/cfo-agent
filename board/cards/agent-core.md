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
- [ ] Chat runs on it and behaves exactly as before: all tests pass and one chat turn is checked by hand
- [x] `summary.py` and the industry classification call Claude through it, so `verify` applies to them too
- [x] A job can only call the local tools it was given
- [x] Tokens, cost and the number of unverified figures are logged for every job run

## Log
- 2026-10-04 (agent): created from the AI CFO Strategy Playbook gap analysis
- 2026-10-04 (agent): priority 3 in Next: every agent job (brief, watch, health check) runs on it.
- 2026-10-05 (agent): claimed. Plan, from the target architecture map (https://claude.ai/artifact/WoBPCezQT64iU5J9qqAG6D): `agent.py` becomes the `agent/` package. `agent/core.py` holds the one Claude client and `run(job, messages)`: request, tool loop, rollback, verify, and a log line per run with tokens, cost and unverified figures. `agent/tools.py` holds the local tools. `agent/jobs/chat.py` is the chat. `summary.py` and `industry.py` keep their prompts and data and call `core.complete()` instead of their own clients. Moving `prompt.py`, `verify.py` and `labels.py` into `agent/`, and moving the summary and classify prompts into `agent/jobs/`, are left for the cards that reshape those (7 for the brief); this card only changes who talks to Anthropic. Job runs go to the log until card 4 gives them a table.
- 2026-10-05 (agent): built on branch `agent-core`. `core.run(job, messages)` runs any job from a `Job` (prompt, allowed local tools, Tripletex/sandbox on or off, output "text" or "json"); `core.complete(job, prompt)` drives it to the end for one-shot jobs. Chat is `agent/jobs/chat.py` and sends a byte-identical request to before (model, system, tools and their order, betas, thinking, effort, fallbacks — compared against the old `agent.py`, with fallbacks on and off). `summary.py` and `industry.py` lost their own clients and call `core.complete()`; a test fails if any other module imports `anthropic`. A job is offered only its own tools, and a call to any other is answered "No such tool" without running. Every run logs one line: `Jobb <navn>: <status> etter N runde(r) · inn, fra cache, til cache, ut · $kostnad · N tall uten kilde`. Starting the real server caught an import loop the tests missed (memory → definitions → industry → agent.core); `agent/tools.py` now imports `cards` and `memory` when a tool runs, and a test loads each module first in a fresh interpreter. Server driven: `/api/health`, `/api/chat` (clean session + error event without Tripletex), `/api/dashboard` (classify ran through the core and failed cleanly with the model unreachable), `/api/summary`. Suite: 226 passed (212 before, 14 new).
- 2026-10-05 (agent): for @edmir — two things changed beyond the move. (1) The summary and the industry classification now send the same server-side refusal fallback the chat already sent (`fallbacks: "default"`); before, a refusal there simply failed. (2) The industry classification's own targets and alarm levels are counted as figures without a source in its log line — correct, since they are the model's judgement of the trade, not the books.
- 2026-10-05 (agent): BLOCKED on one box: "one chat turn is checked by hand" needs the real `.env` (Anthropic key with credits + Tripletex login), which this cloud session does not have. To close it: `./run.sh`, ask one preset question in the chat, check the answer streams as before, and that the server log has a `Jobb chat: done …` line with tokens, a dollar figure and the unverified count. Then tick the box and move the card to Done.
