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

## Log
- 2026-10-30 (agent): created in ## Next on @edmir's call. Since card 53 the brief comes from `Arvaka <cfo@arvaka.no>` and lands in the inbox. Related: card 36 (link the email to the full brief in the app) and card 37 (record opens and link taps), which change what the email holds; worth designing with them in mind.
