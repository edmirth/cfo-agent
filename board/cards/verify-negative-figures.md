---
title: Trace a negative figure however it is written
owner: @edmir
milestone: #agent
created: 2026-11-08
---
## Goal
Card 19. The check that every figure in an answer comes from somewhere
(`backend/verify.py`) flagged "minus 845 481" as having no source, though
−845 481 was in the facts. Only an ASCII hyphen was read as a sign: the agent
writes "minus", our own texts write a real minus sign (U+2212), and Norwegian
often writes a loss as a positive figure ("et underskudd på 845 481"). Each
gave a false "tall uten kilde" on the front page, in the health check, the
morning watch and the job log.

## Done when
- [x] "minus 845 481", "−845 481" and "–845 481" (an en dash with no digit
      or dot before it) are read as negative; "uke 3–5" and "100–200" stay
      ranges
- [x] A figure is traced by its size: the question is whether it came from
      somewhere, not which way it was written. A sign that differs from the
      source is noted on the trace ("fortegn ulikt"), not flagged
- [x] A figure with no source is still flagged
- [x] Tests

## Log
- 2026-11-08 — Built on `verify-negative-figures`. `_signs` turns the written
  minus into one before the figures are read; `Corpus` keeps figures by size
  with the signs it was given them in (`same_sign`), and `check` notes a sign
  that differs. A wrong sign is not an error: telling a loss written in words
  from a wrong figure would be a guess, and bring back the false alarms.
  Suite: 585 passed.
