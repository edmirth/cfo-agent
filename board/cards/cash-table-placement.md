---
title: Place the 13-week cash table where it can actually be read
owner: @edmir
milestone: #ui
created: 2026-10-02
---
## Goal
The thirteen weeks are the answer to "will I make it", and they sat in a third
of a row beside the CFO's prose: a 180-pixel chart, every other week number,
and no figures at all. The table existed only in the retired vanilla frontend.
Give it a full-width section of its own, under the four cards and above the
summary, with the weeks written out so they can be followed one by one.

## Done when
- [x] The thirteen weeks have their own section between the four cards and the
      CFO summary
- [x] The weeks are shown as a table, not only as a curve
- [x] The low-point week is findable without counting rows
- [x] It survives a phone screen

## Log
- 2026-10-02 (agent): new section in `pages/brief.tsx` — chart across the top at
  full width, `CashTable` under it. Columns Uke, Fra, Inn, Ut, Bundet,
  Forventet, the same shape as the table `cashflow.briefing()` puts in the
  prompt, so what the CFO says in the conversation and what is on the screen are
  one picture. The low week carries the row tint and a "tynnest" label, the
  current week says "nå", and a negative balance turns destructive.
- 2026-10-02 (agent): the compact variant of `CashChart` is gone with its only
  caller, and the summary card now runs full width. The 13-week card in the
  right-hand column was removed rather than kept — two readings of the same
  thirteen weeks on one page invite the question which one is right.
- 2026-10-02 (agent): two defects found by looking at it rather than by
  building it. `kr()` printed "-0" for an empty week, because `Math.round(-0)`
  is `-0`; fixed in the formatter, which fixes it everywhere. The chart's y-axis
  was 62px wide, tuned for the narrow column, and broke "800 000" over two
  lines; 74 now.
- 2026-10-02 (agent): and one real bug. A CSS grid rute is by default at least
  as wide as its content, so the six-column table pushed the whole card past the
  right edge of a 390px phone — 498px of card in a 390px window, with Bundet and
  Forventet outside it and nothing to scroll. `grid-cols-[minmax(0,1fr)]` on the
  CardContent lets the rute shrink, and the table now scrolls inside its own
  box: measured 310px box around 571px of content, page itself not scrolling.
- 2026-10-02 (agent): verified against the live ledger at 1440px and 390px,
  no console errors, `tsc --noEmit` clean, 89 Python tests still pass.
