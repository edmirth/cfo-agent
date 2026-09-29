## Board workflow
- The kanban board is board/BOARD.md (Obsidian Kanban format: `## Heading` = column, `- [ ] ...` = card). Columns: Backlog, Next, Doing, Done.
- At the start of a session, read board/BOARD.md.
- You may only pick cards tagged @agent or @either, from ## Next, top card first. Never more than 1 card in ## Doing at a time.
- To claim a card: move its line from ## Next to ## Doing. Moving = cut the exact line and paste it under the target heading. Never reorder or edit other lines.
- If board/cards/<slug>.md exists for the card, read it first and tick its "Done when" boxes as you complete them. Append progress to its ## Log.
- Work on a branch named after the card slug. Commit as you go.
- When finished and tests pass: move the card to ## Done, change `[ ]` to `[x]`, append " ✓ YYYY-MM-DD". Open a PR if a remote exists.
- If blocked: leave the card in ## Doing, write the blocker in the card's Log (or as a sub-bullet under the card line), and stop.
- Never create cards in ## Next or ## Doing yourself. New ideas go to the bottom of ## Backlog tagged @edmir.
