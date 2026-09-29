---
title: Top up the Anthropic credit balance
owner: @edmir
milestone: #ops
created: 2026-09-29
---
## Goal
The account has no credit. Verified directly against the API, not inferred: `POST /v1/messages` returns **400 `invalid_request_error`**, "Your credit balance is too low". A rejected key would be 401 `authentication_error`, so the key is valid and authenticated — the balance is simply empty.

**Note.** The only card here I cannot do any part of. It blocks three features, and the summary has never once produced output — including the company and industry context added this session.

## Done when
- [ ] Credit added at console.anthropic.com -> Plans & Billing
- [ ] The summary card writes `state/summary.json` for the first time
- [ ] Chat answers
- [ ] `/api/dashboard?refresh=true` re-decides the industry KPIs so Egenkapitalandel appears as a tile

## Log
- 2026-09-29 (agent): created
