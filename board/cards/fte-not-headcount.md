---
title: Use FTE from Tripletex instead of headcount in per-employee KPIs
owner: @agent
milestone: #kpi
created: 2026-09-29
---
## Goal
Two KPIs divide by 47 people, many of them part-time in this trade, and judge the result against a full-time benchmark. Tripletex holds the employment percentages.

## Done when
- [x] `omsetning_per_ansatt` and `lonn_per_ansatt` divide by FTE
- [x] The FTE figure comes from Tripletex employment percentages, not a constant
- [x] The definition registry records the change, so older figures keep their old meaning

## Log
- 2026-09-29 (agent): created, transferred from TODO.md
- 2026-10-01 (agent): the premise checked out, and harder than the card said.
  34 current employees — not 47; that figure was stale in the cached profile —
  and **20.0 årsverk**: eleven people on 20 %, four on 40 %, one on 50 %, three
  on 70 %, seven on 80 %, eight on 100 %.

  | | headcount (34) | FTE (20.0) | |
  |---|---|---|---|
  | omsetning_per_ansatt | 547 085 `watch` | **930 045** | `good` |
  | lonn_per_ansatt | 442 386 `good` | **752 057** | `bad` |

  Both tiles flip, and the second flips the wrong way: labour costs 752 057 kr
  per årsverk against a 480 000 target and a 600 000 alarm. That was invisible
  while the denominator was heads.

- 2026-10-01 (agent): fetched with one `tripletex_run_script` call rather than
  34 `get_employee` calls. The percentages live on each employment, so the
  employee list alone cannot give them, and firing one request per person on
  every cold dashboard is the exact shape that was making Tripletex answer 500.
- 2026-10-01 (agent): `calc._per_head` took `headcount` and carried a note
  apologising that heads are not årsverk. It now takes `fte` and the note says
  where the percentages came from. Four definitions bumped — `per_head` and the
  three per-employee KPIs — so figures quoted before today keep their old
  meaning.
- 2026-10-01 (agent): **no fallback to headcount when percentages are missing.**
  An incomplete FTE is worse than none: one person without a percentage counts
  as nobody, shrinking the denominator and flattering every figure — the
  opposite of the error being fixed. Without a complete set the three KPIs
  return nothing and the log says why. Six tests, including that guard.
