---
title: Design the Monday email: Arvaka's brand, built to work as an email
owner: @edmir
milestone: #delivery
created: 2026-10-30
---
## Goal
The Monday brief is the part of Arvaka the CEO sees most, and it goes out as plain HTML from `backend/brief_email.py` (`render_html`), with inline colours and no brand of its own. It should look like it comes from the same company as arvaka.no, and still read well where email is read: Gmail on a phone first, then Outlook and Apple Mail, with images off and in dark mode.

## Done when
- [ ] The brand for email written down: colours, type and logo, taken from arvaka.no (dark green `rgb(15, 54, 42)`, background `#FAFAF9`, Geist and Newsreader, with fallbacks email clients have, since web fonts mostly don't load in email)
- [ ] A design for the brief: header with the logo, the week's light (green/yellow/red) and the lowest point first, the decisions, and a footer with who sent it and how to reach us. @edmir approves it before it is built
- [ ] `render_html` builds it with email-safe HTML: tables for layout, inline styles, no external CSS or scripts, about 600 px wide, readable at phone width
- [ ] Works with images off (the logo has alt text; nothing important is only in an image) and in dark mode
- [ ] The plain-text version still says the same as the HTML
- [ ] Checked by sending it with «Send på e-post nå» to Gmail on a phone and on a desktop, and in at least one of Outlook or Apple Mail; it lands in the inbox, not Spam
- [ ] Tests in `tests/test_brief_email.py` still pass, and cover anything new the layout needs

## Brand for email
From the Arvaka Brand Portfolio v1.0 (Oct 2026), adapted to what mail apps can do.

- **Logo:** the wordmark as live text, «Arvaka» in Newsreader 400 with −4 % tracking, then the forward dot in brand-700 `#135B45`. No logo image, as in the brand's email signature: it reads the same with images off, needs no alt text, and the email stays free of `<img>` (no open pixel).
- **Colour:** 60 % ivory, 30 % ink and warm grays, ≤ 10 % green.
  - Page `#FAFAF9` (ivory), sheet `#FFFFFF`, text `#0F0E0D` (ink), secondary text `#524F49` (gray-700) and `#706D66` (gray-600), hairlines `#E5E5E3` (gray-200).
  - Brand green `#0F362A` (brand-900) for the one button; links `#135B45` (brand-700); tint `#E6EEEA` (brand-100).
  - Lights: `#16A34A` green, `#EAB308` yellow, `#D94636` red, always as a dot and a word (GRØNN / GUL / RØD) in ink, never colour alone. Yellow is too light to be text.
  - Signal lime `#D0F289` only on green or ink, so not in this email.
- **Type:** Newsreader for saying (the week's sentence), Geist for doing (everything else, every number). Never above weight 500. Web fonts mostly don't load in mail, so the stacks fall back the way the signature does: `Newsreader, Georgia, 'Times New Roman', serif` and `Geist, Arial, Helvetica, sans-serif`. Numbers right-aligned.
- **Shape:** one pill button (`border-radius:9999px`, 40 px tall feel, 14 px Geist 500), 6 px sheet corners, 1 px hairlines, no shadows.
- **Dark mode:** `color-scheme: light dark`, and a `@media (prefers-color-scheme: dark)` block for the apps that honour it (Apple Mail, Outlook for Mac, iOS Mail): page `#0F0E0D`, sheet `#1F1D1A`, text `#F2F1F0`, links `#B8C9C1` (brand-on), button `#135B45`. Gmail inverts by itself; the light colours are chosen to invert cleanly.
- **Voice:** outcome, then the number, then the action. Short, Norwegian. A quiet week says so.

## Log
- 2026-10-30 (agent): created in ## Next on @edmir's call. Since card 53 the brief comes from `Arvaka <cfo@arvaka.no>` and lands in the inbox. Related: card 36 (link the email to the full brief in the app) and card 37 (record opens and link taps), which change what the email holds; worth designing with them in mind.
- 2026-11-04 (agent): moved to ## Doing on @edmir's call, branch `email-design`. Brand for email written down above. Next: a mockup for @edmir to approve before `render_html` changes. Defaults taken until told otherwise: ivory header (not a green band), and edmir@arvaka.no as the contact in the footer, since replies to cfo@arvaka.no are card 49.
