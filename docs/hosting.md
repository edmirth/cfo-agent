# Hosting

Two things go on the web, both on Render, both from this repository.

| Address | What | On Render |
|---|---|---|
| `arvaka.no`, `www.arvaka.no` | The landing page, `site/` | A static site, free |
| `app.arvaka.no` | The platform | A web service with a disk. Not set up yet: until it is, the platform runs on the Mac with `run.sh` |

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
