---
title: Put arvaka.no live: booking link, contact email, approved pages, English versions
owner: @edmir
milestone: #platform
created: 2026-10-24
---
## Goal
The landing page is built (`site/`, steps in `docs/hosting.md`), with drafts of Kontakt, Om oss, Samarbeid med regnskapsføreren, Personvern and Databehandleravtale. What is left before arvaka.no points at it is mostly decisions and accounts only @edmir can make.

## Done when
- [ ] A booking page exists, and «Book en samtale» links to it (it goes to /kontakt/ until then)
- [ ] A contact email on arvaka.no works, and is on the pages
- [ ] The five pages are approved: the yellow filled in, `status: utkast` removed in `site-pages/`, `python3 scripts/build_site_pages.py` run
- [ ] The databehandleravtale is reviewed by a lawyer, or replaced by the EU standard clauses (2021/915) with its appendices
- [ ] English versions of the five pages, linked from /en/ (it links to the Norwegian drafts today)
- [ ] Static site on Render with the headers in `docs/hosting.md`; arvaka.no and www.arvaka.no point at it
- [x] The features the page promises and the platform does not have yet are on the board: 10, 25, 27, 40, 42, 47, 48, 49

## Log
- 2026-10-24 (agent): created. The security badges were made true for today (servers in the EU/EEA with every subprocessor in the DPA, invite-only access, traceable figures); BankID and a full audit log are no longer claimed. The feature claims were kept on @edmir's call: they are the offering, and the cards above build them.
- 2026-10-25 (agent): the static site is live on Render (`arvaka-site`), from main after PR #64. DNS at domene.no switched: `arvaka.no` A to `216.24.57.1`, `www` CNAME to the `onrender.com` address, confirmed from every location on dnschecker.org; no AAAA or CAA records. Email stays at domene.no (MX to `mail.arvaka.no`, untouched). www's certificate is issued; arvaka.no's was still pending with "Certificate Error" after the DNS had spread, so the refresh in Render comes next, then Render's support if it stays. Not ticked yet: the headers are not confirmed, and arvaka.no has no certificate.
- 2026-10-29 (agent): checked live: arvaka.no and www have certificates (Google Trust Services, to 2027-01-23), www 301s to arvaka.no, and the three headers in `docs/hosting.md` are served. MX for arvaka.no now points to Google Workspace.
- 2026-10-29 (agent+@edmir): step 1 decided. No company on the pages yet (Arvaka AS is not in Brønnøysund): «Arvaka» and kontakt@arvaka.no as the one responsible, with a note that the company details come when the AS is founded. Email: kontakt@arvaka.no, personvern@ as an alias, on Workspace. Booking: a Google Calendar booking page. DPA: replaced by the EU standard clauses (2021/915) with our appendices; a lawyer can look before the first paying customer. No phone. Om oss without names for now. The deadlines in the drafts kept: 30 days' notice of a new subprocessor, 48 h for a breach, deletion 30 days after the end, enquiries kept 12 months, Oslo tingrett.
- 2026-10-29 (agent+@edmir): kontakt@ and personvern@arvaka.no made as aliases on @edmir's Workspace user; a test email to kontakt@ arrived. The box stays open until the address is on the pages.
- 2026-10-29 (agent+@edmir): booking page made in edmir@arvaka.no's Google Calendar, «Samtale med Arvaka», 30 min with Meet, form asks name and email only: https://calendar.google.com/calendar/appointments/schedules/AcZssZ2ykIEjm0Hdoxhqkt7iwLEYogh-C6NjDWfuLwido-kEd7Y6pdiJWOBFW_GG7UySEvpWNN21EzuK — opens logged out. The box stays open until «Book en samtale» links to it.
