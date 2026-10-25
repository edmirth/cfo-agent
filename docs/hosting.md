# Hosting

Two things go on the web, both on Render, both from this repository.

| Address | What | On Render |
|---|---|---|
| `arvaka.no`, `www.arvaka.no` | The landing page, `site/` | A static site, free |
| `app.arvaka.no` | The platform | A web service with a disk, from `render.yaml`. Ready to set up (card 52); until then the platform runs on the Mac with `run.sh` |

## The landing page

`site/` is the landing page as plain files. There is nothing to build; Render
serves the folder as it is.

| Path | What it is |
|---|---|
| `site/index.html` | The page in Norwegian |
| `site/en/index.html` | The page in English |
| `site/assets/site.css` | The fonts, the page's base styles, its hover and focus states, and the phone nav |
| `site/assets/site.js` | «Slik fungerer det»: the five stories taking turns |
| `site/assets/fonts/` | Geist, Geist Mono and Newsreader, with their licences (SIL Open Font License) |

**Nothing is loaded from anyone else.** The fonts and the image come from the
site itself, so a visitor's browser talks to arvaka.no and nobody else: no
Google Fonts, no CDN, no cookies, no tracking. Keep it that way, or the
privacy policy has to say otherwise.

**Where it came from.** The design was made in Claude Design and exported as
`Arvaka Landing.dc.html`. That file is not a web page on its own: it downloads
React and a JavaScript compiler from unpkg, about 3 MB, and builds the page in
the visitor's browser, so the first view is slow and a search engine may see an
empty page. It was rendered in a browser and saved as HTML, once per language,
with all five story panels kept and the design tool's scripts removed. Checked
screenshot against screenshot, the desktop page matches the design except for
the image, which is re-encoded as WebP (938 KB to 36 KB). Two things differ on
purpose:

- **Phones.** The design's nav is wider than a phone screen, so the page
  scrolled sideways. Under 640 px the section links and the nav's booking
  button are hidden; the hero carries the call to action.
- **Focus ring.** It shows for keyboard focus only, not after every click.

**Changing it.** Text is edited in the two HTML files directly. The design's
styles are inline, so a word is changed where it stands. A new design from
Claude Design is converted again rather than merged by hand.

**The text pages.** Kontakt, Om oss, Samarbeid med regnskapsføreren,
Personvern and Databehandleravtale are written in `site-pages/`, one file
each, and built into `site/<slug>/` with the front page's own nav and footer:

    python3 scripts/build_site_pages.py

Edit the file in `site-pages/`, never the built page, and run the script
after a change to the front page's nav or footer too. A page marked
`status: utkast` shows a draft banner, marks what is missing in yellow and
asks search engines to stay away; remove the line when the page is approved.
They are in Norwegian only for now, and the English front page links to them.

### On Render

1. **New → Static Site**, this repository, branch `main`.
2. **Build command:** leave empty. **Publish directory:** `site`.
3. **Settings → Custom Domains:** add `arvaka.no` and `www.arvaka.no`. Render
   shows the DNS record each one needs.
4. **Settings → Headers**, for the path `/*`:

   | Header | Value |
   |---|---|
   | `X-Content-Type-Options` | `nosniff` |
   | `Referrer-Policy` | `strict-origin-when-cross-origin` |
   | `Content-Security-Policy` | `default-src 'self'; style-src 'self' 'unsafe-inline'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'` |

   The policy lets the page load only from itself. `'unsafe-inline'` is for
   styles only, because the design's styles are inline; scripts stay
   `'self'`. The page has been checked under this policy with no violations.

### DNS at domene.no

In domene.no's control panel, under DNS for `arvaka.no`:

| Name | Type | Value |
|---|---|---|
| `arvaka.no` (often written `@`) | A | The IP address Render shows |
| `www` | CNAME | The `….onrender.com` address Render shows |

Leave any MX records as they are: they deliver email to `@arvaka.no`. Once the
records answer, Render issues the HTTPS certificates by itself, which takes
from minutes to a few hours. Render's Hobby plan includes two custom domains;
each one beyond that costs $0.25 a month.

## The platform

One copy of the platform per pilot company, each a Render web service with
its own disk, settings and Tripletex login. SQLite stays until one shared app
is built (`docs/database.md`). The service is described in `render.yaml` and
built from the `Dockerfile`.

| Where | What is there |
|---|---|
| The image | The code and the built frontend. Rebuilt on every deploy; nothing in it survives one |
| The disk, at `/app/state` | Everything the company has: `cfo.db`, `company.md` and the files beside it, `tripletex.json` (the rotated Tripletex login), `backups/` |
| Render's settings | The keys and the first Tripletex login. Never in the repository, never in the image |
| Supabase Storage | The nightly copy, encrypted. Supabase cannot read it |

**What is different from the Mac.** The server refuses to start with
`CFO_AUTH=off` (Render sets `RENDER`). The rotated Tripletex login is kept on
the disk, not in `.env`. There is one worker and no `--reload`. A deploy
restarts the server, so the page is away for a minute or so: a service with a
disk cannot run two copies side by side.

### Before the first deploy

1. **A place for the copies outside Render.** In Supabase, best a project of
   its own (say `arvaka-backups`, region Stockholm), so the key the server
   holds reaches the backups and not the login. **Storage → New bucket**,
   name `backups`, **private**. Note the project's URL and, under **Project
   Settings → API keys**, its `service_role` key.
2. **The encryption key.** On the Mac:

       ./.venv/bin/python scripts/backup.py key

   Put it in a password manager now. Without it the copies in Supabase cannot
   be opened, by anyone.
3. **The Tripletex login.** For the company's own Tripletex, from a Mac:
   `scripts/oauth_login.py` writes `TRIPLETEX_CLIENT_ID` and
   `TRIPLETEX_REFRESH_TOKEN` to `.env`. It writes to *this* folder's `.env`,
   so for another company than the one the Mac runs, do it in a separate copy
   of the repository, or the Mac's own login is replaced.

### First deploy

1. Render: **New → Blueprint**, this repository, branch `main`. Render reads
   `render.yaml` and shows the service `arvaka-app` with a 1 GB disk.
2. Fill in the settings it asks for:

   | Setting | Where it comes from |
   |---|---|
   | `ANTHROPIC_API_KEY` | console.anthropic.com |
   | `COMPANY_NAME` | The company's name, as on its letters |
   | `TRIPLETEX_CLIENT_ID`, `TRIPLETEX_REFRESH_TOKEN` | Step 3 above |
   | `SUPABASE_URL`, `SUPABASE_ANON_KEY` | The login project, as in `.env` |
   | `CFO_OWNER_EMAIL` | The CEO's email; more separated by commas |
   | `RESEND_API_KEY`, `CFO_MAIL_FROM` | As in `.env` (card 53 moves the sender to `cfo@arvaka.no`) |
   | `CFO_BACKUP_KEY` | Step 2 above |
   | `SUPABASE_SERVICE_KEY`, `CFO_BACKUP_SUPABASE_URL` | Step 1 above |

3. **Apply.** The first build takes a few minutes. The health check is
   `/api/auth/config`; Render waits for it before it sends anyone there.
4. **The address.** In the service, **Settings → Custom Domains**, add
   `app.arvaka.no`. At domene.no, a `CNAME` record named `app` pointing to
   the service's `….onrender.com` address.
5. **The login knows the address.** In the login project in Supabase,
   **Authentication → URL Configuration**: set the Site URL to
   `https://app.arvaka.no` and add it under Redirect URLs. Without it a login
   link sends the CEO back to the Mac's address.

After that, every merge to `main` deploys by itself.

### Adding a pilot company

Copy the service in `render.yaml` with a new `name` (say `arvaka-lindeskar`)
and a disk of its own, merge, and Render offers the new service under the
Blueprint. Fill in its settings as above, with the company's own Tripletex
login and CEO, and give it an address of its own. The encryption key and the
backup project can be shared: each company's copies are in a folder named
after it.

### Moving `state/` from the Mac

The Mac and the server must never run at the same time on one Tripletex
login: each renewal replaces the token, and the other is locked out.

1. Stop `run.sh` on the Mac.
2. Take a copy and send it out, with the backup settings in the Mac's `.env`:

       ./.venv/bin/python scripts/backup.py now

3. Put the Mac's newest Tripletex token in Render's `TRIPLETEX_REFRESH_TOKEN`.
   It is in `state/tripletex.json` (or `.env`, if that file is not there yet):

       python3 -c "import json; print(json.load(open('state/tripletex.json'))['refresh_token'])"

4. In the service on Render, **Shell**:

       python scripts/backup.py list
       python scripts/backup.py fetch <the newest name>

5. **Manual Deploy → Restart service.** At start-up the copy is put in place
   (see below), and the server opens on the Mac's data.
6. Do not start `run.sh` on the Mac again for this company.

### Restoring a backup

A copy is put back by leaving it in `state/restore/` and restarting. At
start-up, before anything opens the database, the server checks the copy,
moves what is there now into `state/before-restore-<time>/`, and puts the
copy in its place. A copy that will not open or check out is left alone, the
server starts on the data it has, and the log says why.

- **From the disk**, a night back: in the Shell,
  `mkdir -p state/restore && cp state/backups/<name> state/restore/`, then
  restart.
- **From outside Render**, the disk lost or new: in the Shell,
  `python scripts/backup.py list`, then `fetch <name>`, then restart. The
  service needs `CFO_BACKUP_KEY`, or the copy cannot be opened.
- **Just to look**, on the Mac:
  `./.venv/bin/python scripts/backup.py open <copy> <new folder>` unpacks it,
  and DB Browser for SQLite opens the `cfo.db` inside.

Nothing is deleted by a restore. Once the restored data looks right, the
`before-restore-…` folder can go.

### Sikkerhetskopi (the nightly backup)

Every night at 02:00 (`CFO_BACKUP_AT`) the job `backup` runs: a copy of
`cfo.db`, through SQLite's own backup and checked, packed with `company.md`,
`definitions.json`, `profile.json` and `summary.json` into
`state/backups/<company>-<date>.tar.gz`. The last 14 are kept. Then the same
file is encrypted and sent to the `backups` bucket, where the last 14 are
kept too. A night it could not send says so on the front page. The Tripletex
token is not in the copy: it rotates, so a copy of it is stale by the next
renewal.

